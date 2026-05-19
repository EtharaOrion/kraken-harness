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

"""Regression tests pinning the TypeScript harness correctness fixes.

Mirrors the TEST-PER-COMMIT pattern from the sibling audit file, keeping
only the TS-applicable subset. Each test locks one previously-broken
behavior so it cannot silently regress: registry guard on multiarch
push, workload-validate Dockerfile invokes vitest / tsc --noEmit, the
base ts image installs no native toolchain, the eval platform is
hardcoded to linux/amd64 (linux/x86_64), the scrape backoff sleep table
survives, make_test_spec_ts guarantees test_patch on the instance dict,
and env + instance Dockerfiles emit the same --platform value (mismatch
fix).

Implemented via source inspection / direct function calls so the tests
run without Docker.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BUILD_AND_VALIDATE_TS = _PROJECT_ROOT / "scripts" / "build_and_validate_images_ts.py"


# --- registry guard (build_and_validate_images_ts) -------------------------
# Sibling audit commit: registry guard, workload validation, parallel image
# validate.

def test_build_and_validate_images_ts_registers_multiarch_and_registry_flags():
    """The argparse must define both ``--build-multiarch`` and ``--registry``."""
    src = _BUILD_AND_VALIDATE_TS.read_text()
    tree = ast.parse(src)
    add_argument_strings: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            add_argument_strings.append(node.args[0].value)
    assert "--build-multiarch" in add_argument_strings
    assert "--registry" in add_argument_strings


def test_build_and_validate_images_ts_guards_multiarch_without_registry():
    """``--build-multiarch`` without ``--registry`` must abort: pushing an
    unqualified image name targets docker.io/library and 401/403s."""
    src = _BUILD_AND_VALIDATE_TS.read_text()
    # The exact guard branch from the audit commit. Keeping it strict so
    # any refactor that loses the guard fails this test loudly.
    assert "if args.build_multiarch and not args.registry:" in src
    guard_tail = src.split("if args.build_multiarch and not args.registry:", 1)[1]
    head = guard_tail.split("\n\n", 1)[0]
    assert "parser.error" in head, (
        "Multiarch-without-registry guard must call parser.error to exit non-zero"
    )


# --- workload validation Dockerfile ---------------------------------------
# Sibling audit commit: registry guard, workload validation, parallel image
# validate.

def test_workload_validate_dockerfile_cheap_invokes_tsc_noemit():
    """Cheap mode validates with ``tsc --noEmit``."""
    from swefficiency.harness.dockerfiles_ts import (
        get_dockerfile_workload_validate_ts,
    )

    df = get_dockerfile_workload_validate_ts("cheap")
    assert "tsc --noEmit" in df
    assert "FROM sweb.base.ts:latest" in df
    assert "workload.bench.ts" in df


def test_workload_validate_dockerfile_full_runs_vitest_bench():
    """Full mode runs the real Vitest bench."""
    from swefficiency.harness.dockerfiles_ts import (
        get_dockerfile_workload_validate_ts,
    )

    df = get_dockerfile_workload_validate_ts("full")
    assert "vitest" in df
    assert "FROM sweb.base.ts:latest" in df
    assert "workload.bench.ts" in df


# --- sweb.base.ts must NOT install a native toolchain ----------------------
# Sibling audit commit: fix scrape, image build, discovery backoff, version
# detection (image build half).

def test_base_ts_image_has_no_native_toolchain():
    """The ts base image is a pure Node 20 image. The native-toolchain tokens
    (forbidden literals: a C++ compiler, cmake, gtest, gbench) must not appear
    in the rendered Dockerfile -- they belong to the sibling pipeline only."""
    from swefficiency.harness.dockerfiles_ts import (
        get_dockerfile_base_multiarch_ts,
    )

    df = get_dockerfile_base_multiarch_ts()
    forbidden = ["g++", "cmake", "gtest", "gbench"]
    for tok in forbidden:
        assert tok not in df, (
            f"sweb.base.ts Dockerfile must not contain {tok!r}; got:\n{df}"
        )


# --- eval platform pinned to linux/amd64 -----------------------------------
# Sibling audit commit: fix eval platform mismatch and workload lib linking
# (eval platform half).

def test_test_spec_ts_pins_linux_amd64_platform():
    """``TestSpecTs.platform`` returns ``linux/x86_64`` exactly.

    The sibling cpp pipeline picked ``linux/x86_64`` deliberately in commit
    ad247c7 ("fix eval platform mismatch") and the ts harness must match.
    Accepting ``linux/amd64`` as a synonym sounds harmless but lets the
    constant drift; the env, instance, and runtime platform strings must
    all be byte-identical for buildx to keep the multi-arch graph collapsed
    to a single arch.

    Assertion targets the literal in ``return "..."`` (not the full source)
    so explanatory comments mentioning ``linux/amd64`` don't shadow the check.
    """
    import re

    from swefficiency.harness import test_spec_ts

    fget = test_spec_ts.TestSpecTs.platform.fget
    assert fget is not None, "TestSpecTs.platform must be a readable property"
    src = inspect.getsource(fget)
    return_match = re.search(r"return\s+['\"]([^'\"]+)['\"]", src)
    assert return_match is not None, f"could not find return literal in:\n{src}"
    returned = return_match.group(1)
    assert returned == "linux/x86_64", (
        f"TestSpecTs.platform must return exactly 'linux/x86_64', got {returned!r}"
    )


# --- scrape backoff sleep table preserved ----------------------------------
# Sibling audit commit: fix scrape, image build, discovery backoff, version
# detection (backoff half).

def test_discover_repos_ts_rate_limit_wait_keeps_backoff_table():
    """``_rate_limit_wait`` handles all three GitHub 403 cases with the
    audited fixed-value sleep table:

    * Retry-After present -> ``int(retry_after) + 1`` (60s fallback on
      malformed header).
    * Primary limit exhausted -> wait until ``X-RateLimit-Reset`` + 5s.
    * 403 with no rate-limit headers -> ``time.sleep(30)``.
    """
    from swefficiency.collect import discover_repos_ts

    src = inspect.getsource(discover_repos_ts._rate_limit_wait)
    assert "Retry-After" in src
    assert "X-RateLimit-Reset" in src
    assert "X-RateLimit-Remaining" in src
    # Retry-After fallback when header is non-numeric.
    assert "sleep_for = 60" in src
    # Primary reset + 5s slack.
    assert "+ 5" in src
    # Bare-403 fallback.
    assert "time.sleep(30)" in src


def test_discover_repos_ts_gh_get_exponential_backoff():
    """``_gh_get`` uses ``2 ** attempt`` on RequestException + 5xx."""
    from swefficiency.collect import discover_repos_ts

    src = inspect.getsource(discover_repos_ts._gh_get)
    assert "2 ** attempt" in src
    # Both transient branches must be present.
    assert "RequestException" in src
    assert "502" in src and "503" in src and "504" in src


# --- make_test_spec_ts guarantees test_patch on the instance dict ----------
# Sibling audit commit: guarantee test_patch on the instance before building
# scripts.

def test_make_test_spec_ts_guarantees_test_patch_key():
    """make_test_spec_ts must populate ``instance['test_patch']`` before
    handing the dict to helpers that bracket-access it (the shared
    get_test_directives, called by get_correctness_script_list_ts).

    Source-inspected: the full call path runs through dynamic_specs / docker
    and is too heavy for an offline unit test."""
    from swefficiency.harness import test_spec_ts

    src = inspect.getsource(test_spec_ts.make_test_spec_ts)
    assert 'instance.get("test_patch"' in src, (
        "make_test_spec_ts must call instance.get('test_patch', ...) before "
        "any helper bracket-accesses the key"
    )
    # The merge-back puts the key into the instance dict so downstream
    # helpers see it via __getitem__.
    assert '"test_patch":' in src


# --- env image platform matches instance image platform -------------------
# Sibling audit commit: fix eval platform mismatch and workload lib linking
# (mismatch half).

def test_env_and_instance_dockerfiles_share_platform_pin():
    """The env image and instance image Dockerfiles must bake in the
    exact same ``--platform`` value. Otherwise the instance layer FROMs
    an env image of the wrong arch and buildx silently fans out a
    multi-arch graph that fails at run time."""
    from swefficiency.harness.dockerfiles_ts import (
        get_dockerfile_env_ts,
        get_dockerfile_instance_ts,
    )

    platform = "linux/x86_64"
    env_df = get_dockerfile_env_ts(platform)
    inst_df = get_dockerfile_instance_ts(platform, "sweb.env.ts.testkey:latest")
    pat = f"FROM --platform={platform}"
    assert pat in env_df, env_df
    assert pat in inst_df, inst_df
    # And the FROM in the instance image references the env image (not the
    # base image directly) -- the layering must be base -> env -> instance.
    assert "sweb.env.ts.testkey:latest" in inst_df
