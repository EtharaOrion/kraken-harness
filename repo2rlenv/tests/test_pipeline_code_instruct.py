"""code_instruct — diff builder, dockerfile shape, pipeline contract.

Sampler / parser / decontam are tested in test_oss_instruct_helpers.py.
Here we cover the pipeline-level pure-Python pieces and the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo2rlenv.pipelines.code_instruct import (
    CodeInstructPipeline,
    _all_tests_passed,
    _build_task_module_router,
    _make_solution_diff,
    build_code_instruct_dockerfile,
)
from repo2rlenv.spec.options import CodeInstructOptions

# ---------------------------------------------------------------------------
# _make_solution_diff — gold patch carries ONLY task_module.py.
# The synthesized test file is staged separately via tests/ (HarborTask.aux_files)
# so non-oracle agents can reach it. See known-issues/code_instruct-test-staging.md.
# ---------------------------------------------------------------------------


def test_solution_diff_has_single_header():
    diff = _make_solution_diff(
        task_module_code="def add(x, y):\n    return x + y\n",
    )
    assert diff.count("diff --git ") == 1
    assert "diff --git a/task_module.py b/task_module.py" in diff


def test_solution_diff_excludes_test_file():
    """Regression: the test file MUST NOT appear in the gold patch.

    Bundling it under solution/patch.diff makes the file invisible to every
    non-oracle Harbor agent (`nop`, `claude-code`, …) because Harbor only
    stages solution/ for the OracleAgent.
    """
    diff = _make_solution_diff(
        task_module_code="def add(x, y):\n    return x + y\n",
    )
    assert "test_r2e_" not in diff
    assert "diff --git a/test_" not in diff


def test_solution_diff_marks_new_file():
    diff = _make_solution_diff(task_module_code="x = 1\n")
    assert diff.count("new file mode") == 1
    assert diff.count("--- /dev/null") == 1


def test_solution_diff_hunk_line_count():
    diff = _make_solution_diff(task_module_code="line1\nline2\nline3\n")
    assert "@@ -0,0 +1,3 @@" in diff


def test_solution_diff_handles_missing_trailing_newline():
    diff = _make_solution_diff(task_module_code="x = 1")  # no trailing newline
    assert "\\ No newline at end of file" in diff


def test_solution_diff_rejects_empty_code():
    """Empty / whitespace-only code produces `@@ -0,0 +1,0 @@` which git apply
    rejects as a corrupt patch. Regression for review finding B2.
    """
    with pytest.raises(ValueError, match="empty"):
        _make_solution_diff(task_module_code="")
    with pytest.raises(ValueError, match="empty"):
        _make_solution_diff(task_module_code="   \n\n  \n")


# ---------------------------------------------------------------------------
# build_code_instruct_dockerfile
# ---------------------------------------------------------------------------


def test_dockerfile_minimal_shape():
    df = build_code_instruct_dockerfile("local/img:abc")
    assert df.startswith("# Auto-generated") or "FROM local/img:abc" in df
    assert "FROM local/img:abc" in df
    # No patching at build time (unlike pr_runtime / mutation_bugs)
    assert "git apply" not in df
    # Defensive git install (so `git config` works inside container)
    assert "apt-get install" in df


# ---------------------------------------------------------------------------
# _all_tests_passed
# ---------------------------------------------------------------------------


def test_all_tests_passed_detects_passed_summary():
    log = "==== 3 passed in 0.12s ===="
    assert _all_tests_passed(log)


def test_all_tests_passed_rejects_failed():
    log = "==== 1 failed, 2 passed in 0.12s ===="
    assert not _all_tests_passed(log)


def test_all_tests_passed_rejects_no_collected():
    log = "ERROR: collected 0 items"
    assert not _all_tests_passed(log)


def test_all_tests_passed_rejects_collection_error():
    log = "ImportError: No module named 'task_module'\nERRORS\ncollected 0 items / 1 error\n"
    assert not _all_tests_passed(log)


def test_all_tests_passed_rejects_errors_with_passed():
    """`2 passed, 1 error` means a test errored during collection/setup —
    accepting this would emit a task with a broken verifier. Regression
    for review finding S1.
    """
    assert not _all_tests_passed("==== 2 passed, 1 error in 0.12s ====")
    assert not _all_tests_passed("==== 1 passed, 3 errors in 0.12s ====")


def test_all_tests_passed_rejects_zero_passed():
    assert not _all_tests_passed("==== 0 passed in 0.01s ====")


# ---------------------------------------------------------------------------
# Pipeline contract
# ---------------------------------------------------------------------------


def test_code_instruct_requires_bootstrap_attr():
    assert CodeInstructPipeline.requires_bootstrap is True


def test_code_instruct_rejects_missing_bootstrap():
    from repo2rlenv.spec.input import (
        GenerationInput,
        LLMSpec,
        OutputSpec,
        PipelineName,
        PipelineSpec,
        RepoSpec,
    )

    gen_input = GenerationInput(
        repo=RepoSpec(url="huggingface/trl"),
        pipeline=PipelineSpec(name=PipelineName.CODE_INSTRUCT, options={}),
        llm=LLMSpec(provider="anthropic", model="claude-sonnet-4-6"),
        output=OutputSpec(destination="./out", org="x", dataset_name="y"),
    )
    with pytest.raises(RuntimeError, match="requires a BootstrapResult"):
        CodeInstructPipeline(gen_input, CodeInstructOptions(), bootstrap=None)


def test_code_instruct_options_defaults():
    opts = CodeInstructOptions()
    assert opts.limit == 50
    assert opts.seed_min_loc == 30
    assert opts.seed_max_loc == 200
    assert opts.require_test_fails_without_oracle is True
    assert opts.require_test_passes_with_oracle is True
    # Cost cap mirrors BootstrapSpec — None = unbounded (regression for B6).
    assert opts.max_llm_spend_usd is None
    assert CodeInstructOptions(max_llm_spend_usd=1.50).max_llm_spend_usd == 1.50


# ---------------------------------------------------------------------------
# _build_task_module_router — runtime auto-router shim baked into tests/test.sh
# ---------------------------------------------------------------------------


def _run_shim(shim_cmd: str, root: Path) -> tuple[int, str, str]:
    """Execute the router shim with R2E_ROUTER_ROOT pointing at `root`."""
    import os
    import subprocess

    env = {**os.environ, "R2E_ROUTER_ROOT": str(root)}
    proc = subprocess.run(
        ["bash", "-c", shim_cmd],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _init_git_repo(root: Path, baseline_files: dict[str, str]) -> None:
    """Initialise a git repo at `root` with the given pre-existing files committed.

    Subsequent files (the "agent's work") are added to the working tree
    AFTER this commit, so `git ls-files --others --modified` enumerates
    only the agent-added/modified files — exactly the isolation the
    router shim depends on.
    """
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    for rel, content in baseline_files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=root, check=True)


def test_router_returns_single_line_command():
    shim = _build_task_module_router(["foo"])
    assert "\n" not in shim, "router must be a single shell command for && chaining"
    assert shim.startswith("echo ") and "base64" in shim and "python3" in shim


def test_router_creates_task_module_from_agent_file(tmp_path: Path):
    """S1 happy path — agent wrote solution.py defining the expected fn."""
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    (tmp_path / "solution.py").write_text("def render_frames(t, n):\n    return [t] * n\n")
    shim = _build_task_module_router(["render_frames"])
    code, _, stderr = _run_shim(shim, tmp_path)
    assert code == 0, f"shim must always exit 0; stderr={stderr!r}"
    target = tmp_path / "task_module.py"
    assert target.exists(), "router did not create task_module.py"
    body = target.read_text()
    assert "from solution import *" in body
    assert "[task_module_router]" in stderr


def test_router_noop_when_task_module_already_exists(tmp_path: Path):
    """S3 — agent already wrote task_module.py; router must NOT overwrite."""
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    target = tmp_path / "task_module.py"
    original = "def render_frames(t, n):\n    return ['agent-wrote-this']\n"
    target.write_text(original)
    shim = _build_task_module_router(["render_frames"])
    code, _, _ = _run_shim(shim, tmp_path)
    assert code == 0
    assert target.read_text() == original, "router clobbered agent's task_module.py"


def test_router_noop_when_no_match(tmp_path: Path):
    """S2 — agent wrote nothing useful; router silently exits 0."""
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    (tmp_path / "scratch.py").write_text("def unrelated(): return 1\n")
    shim = _build_task_module_router(["render_frames"])
    code, _, _ = _run_shim(shim, tmp_path)
    assert code == 0
    assert not (tmp_path / "task_module.py").exists()


def test_router_ignores_unmodified_repo_files(tmp_path: Path):
    """S4 (critical) — pre-existing repo file defining the same name must
    NOT be selected. The bootstrap clones repos like aws-cli into /workspace
    and many of them have functions with common names (`process`, `run`).
    Only agent-added/modified files (via `git ls-files --others --modified`)
    are valid candidates.
    """
    baseline = {"vendored/lib.py": "def render_frames(t, n):\n    return ['vendored']\n"}
    _init_git_repo(tmp_path, baseline)
    shim = _build_task_module_router(["render_frames"])
    code, _, _ = _run_shim(shim, tmp_path)
    assert code == 0
    assert not (tmp_path / "task_module.py").exists(), (
        "router incorrectly routed to pre-existing repo file"
    )


def test_router_ignores_test_files_and_conftest(tmp_path: Path):
    """Test files defining the same name (likely the verifier itself)
    must not be routed to — they would create a circular import.
    """
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    (tmp_path / "test_solution.py").write_text("def render_frames(t, n): return []\n")
    (tmp_path / "conftest.py").write_text("def render_frames(t, n): return []\n")
    shim = _build_task_module_router(["render_frames"])
    code, _, _ = _run_shim(shim, tmp_path)
    assert code == 0
    assert not (tmp_path / "task_module.py").exists()


def test_router_handles_class_definition(tmp_path: Path):
    """Tests sometimes import classes — router should match ClassDef too."""
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    (tmp_path / "lib.py").write_text("class Spinner:\n    pass\n")
    shim = _build_task_module_router(["Spinner"])
    code, _, _ = _run_shim(shim, tmp_path)
    assert code == 0
    assert (tmp_path / "task_module.py").exists()
    assert "from lib import *" in (tmp_path / "task_module.py").read_text()


def test_router_ignores_nested_methods(tmp_path: Path):
    """A method NESTED inside a class (or function) with the expected name
    must NOT trigger routing. `from <mod> import *` only exposes module-level
    names, so routing on a nested match would create a `task_module.py` that
    fails to import the expected symbol — yielding silent reward 0.

    Regression for code review finding #2 (ast.walk false positive).
    """
    _init_git_repo(tmp_path, {"README.md": "repo\n"})
    (tmp_path / "lib.py").write_text(
        "class Unrelated:\n    def render_frames(self, t, n):\n        return [t] * n\n"
    )
    shim = _build_task_module_router(["render_frames"])
    code, _, stderr = _run_shim(shim, tmp_path)
    assert code == 0, f"shim must always exit 0; stderr={stderr!r}"
    assert not (tmp_path / "task_module.py").exists(), (
        "router routed to a file whose only match is a nested method — "
        "`from lib import *` will not expose `render_frames` so the test "
        "would fail with AttributeError"
    )
