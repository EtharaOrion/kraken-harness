"""Harbor task emitter writes the right files."""

from __future__ import annotations

import tomllib
from pathlib import Path
from uuid import UUID

from repo2rlenv.emitter.harbor import HarborTask, write_harbor_task


def _make_task(name: str = "demo__repo-1") -> HarborTask:
    return HarborTask(
        name=name,
        org="myorg",
        description="example",
        instruction="# Issue\n\nfix the bug",
        oracle_diff="--- a/x.py\n+++ b/x.py\n@@\n-1\n+2\n",
        repo2env={
            "pipeline": "pr_diff",
            "pipeline_version": "0.1.0",
            "repo": "demo/repo",
        },
    )


def test_writes_full_directory(tmp_path: Path):
    task = _make_task()
    out = write_harbor_task(task, tmp_path)
    assert out.parent == tmp_path
    UUID(out.name)  # dir name is a valid UUID
    assert (out / "task.toml").is_file()
    assert (out / "instruction.md").is_file()
    assert (out / "solution" / "patch.diff").is_file()


def test_task_toml_is_valid_toml_with_harbor_layout(tmp_path: Path):
    task = _make_task()
    out = write_harbor_task(task, tmp_path)
    data = tomllib.loads((out / "task.toml").read_text())
    assert data["version"] == "1.0"
    assert data["task"]["name"] == "myorg/demo__repo-1"
    UUID(out.name)  # dir is UUID, slug lives in task.toml only
    r2e = data["metadata"]["repo2env"]
    assert r2e["pipeline"] == "pr_diff"
    assert r2e["spec_version"] == "0.2.0"
    assert r2e["content_hash"].startswith("sha256:")
    assert "diff_similarity" in r2e["reward_kinds"]


def test_instruction_and_oracle_round_trip(tmp_path: Path):
    task = _make_task()
    out = write_harbor_task(task, tmp_path)
    assert (out / "instruction.md").read_text() == task.instruction
    assert (out / "solution" / "patch.diff").read_text() == task.oracle_diff


def test_solve_sh_emitted_and_executable(tmp_path: Path):
    """Harbor's oracle agent runs solve.sh in the container — must exist + be +x."""
    task = _make_task()
    out = write_harbor_task(task, tmp_path)
    solve = out / "solution" / "solve.sh"
    assert solve.is_file()
    assert solve.stat().st_mode & 0o111  # executable
    content = solve.read_text()
    assert content.startswith("#!/bin/bash")
    # Must reference patch.diff (the canonical oracle artifact)
    assert "patch.diff" in content
    assert "git apply" in content


def test_content_hash_is_deterministic(tmp_path: Path):
    a = write_harbor_task(_make_task("a"), tmp_path / "a")
    b = write_harbor_task(_make_task("b"), tmp_path / "b")
    da = tomllib.loads((a / "task.toml").read_text())
    db = tomllib.loads((b / "task.toml").read_text())
    # Same instruction + oracle ⇒ same content_hash, regardless of name.
    assert da["metadata"]["repo2env"]["content_hash"] == db["metadata"]["repo2env"]["content_hash"]


def test_writes_environment_and_test_script_when_provided(tmp_path: Path):
    """Sandbox-required tasks (pr_runtime) emit Dockerfile + test.sh."""
    task = _make_task("sandbox-task")
    task.environment_dockerfile = "FROM ubuntu:24.04\nWORKDIR /workspace\n"
    task.test_script = "#!/bin/bash\nset -e\npytest -x\n"
    out = write_harbor_task(task, tmp_path)

    assert (out / "environment" / "Dockerfile").is_file()
    assert (out / "tests" / "test.sh").is_file()
    assert (out / "environment" / "Dockerfile").read_text() == task.environment_dockerfile
    assert (out / "tests" / "test.sh").read_text() == task.test_script
    # test.sh must be executable so Harbor can run it directly
    assert (out / "tests" / "test.sh").stat().st_mode & 0o111

    # reward_kinds upgrades to test_execution primary when test_script is present
    data = tomllib.loads((out / "task.toml").read_text())
    assert data["metadata"]["repo2env"]["reward_kinds"] == ["test_execution", "diff_similarity"]


def test_writes_aux_files_under_task_dir(tmp_path: Path):
    """Aux files (e.g. tests/verifier.py, tests/f2p.json) are written verbatim."""
    task = _make_task("aux-task")
    task.test_script = "#!/bin/bash\ntrue\n"
    task.aux_files = {
        "tests/verifier.py": "print('hi')\n",
        "tests/f2p.json": '["a::b"]',
        "tests/p2p.json": "[]",
    }
    out = write_harbor_task(task, tmp_path)
    assert (out / "tests" / "verifier.py").read_text() == "print('hi')\n"
    assert (out / "tests" / "f2p.json").read_text() == '["a::b"]'
    assert (out / "tests" / "p2p.json").read_text() == "[]"


def test_aux_file_path_cannot_escape_task_dir(tmp_path: Path):
    """Defensive: an aux_file path that escapes the task dir is rejected."""
    import pytest

    task = _make_task("escape-task")
    task.aux_files = {"../../etc/evil": "x"}
    with pytest.raises(ValueError, match="escapes task dir"):
        write_harbor_task(task, tmp_path)


def test_omits_environment_and_test_script_when_absent(tmp_path: Path):
    """Lite tasks (pr_diff) don't write environment/ or tests/."""
    task = _make_task("lite-task")
    out = write_harbor_task(task, tmp_path)
    assert not (out / "environment").exists()
    assert not (out / "tests").exists()


def test_reproducibility_subtable_seeded_for_runtime_tasks(tmp_path: Path):
    """v0.8.2.post3: tasks with environment/Dockerfile get the local_only marker."""
    task = _make_task("rt-task")
    task.environment_dockerfile = (
        "FROM local/r2e-bootstrap/pallets__click:a1b2c3d4e5f6\nWORKDIR /workspace\n"
    )
    task.test_script = "#!/bin/bash\npytest\n"
    out = write_harbor_task(task, tmp_path)
    data = tomllib.loads((out / "task.toml").read_text())
    repro = data["metadata"]["repo2env"]["reproducibility"]
    assert repro["mode"] == "local_only"
    assert repro["image_ref"] == "local/r2e-bootstrap/pallets__click:a1b2c3d4e5f6"
    assert repro["image_visibility"] == "private"


def test_no_reproducibility_subtable_for_lite_tasks(tmp_path: Path):
    """pr_diff tasks (no environment/) skip the subtable entirely."""
    task = _make_task("lite-task")
    out = write_harbor_task(task, tmp_path)
    data = tomllib.loads((out / "task.toml").read_text())
    assert "reproducibility" not in data["metadata"]["repo2env"]


def test_reproducibility_caller_override_preserved(tmp_path: Path):
    """If the pipeline pre-populates reproducibility, the emitter doesn't overwrite."""
    task = _make_task("custom-task")
    task.environment_dockerfile = "FROM ubuntu\n"
    task.repo2env["reproducibility"] = {
        "mode": "registry",
        "image_ref": "ghcr.io/foo/bar@sha256:abc",
    }
    out = write_harbor_task(task, tmp_path)
    data = tomllib.loads((out / "task.toml").read_text())
    repro = data["metadata"]["repo2env"]["reproducibility"]
    assert repro["mode"] == "registry"
    assert repro["image_ref"] == "ghcr.io/foo/bar@sha256:abc"


def test_explicit_uuid_dir_naming(tmp_path: Path):
    task = _make_task()
    task.task_uuid = "0c8f28fe-c9cb-4291-8cfc-8e683f08039b"
    out = write_harbor_task(task, tmp_path)
    assert out.name == "0c8f28fe-c9cb-4291-8cfc-8e683f08039b"
    data = tomllib.loads((out / "task.toml").read_text())
    assert data["task"]["name"] == "myorg/demo__repo-1"


def test_auto_generated_uuid_dir(tmp_path: Path):
    task = _make_task()
    out = write_harbor_task(task, tmp_path)
    UUID(out.name)
    data = tomllib.loads((out / "task.toml").read_text())
    assert data["task"]["name"] == "myorg/demo__repo-1"


def test_two_tasks_get_distinct_uuids(tmp_path: Path):
    a = write_harbor_task(_make_task("a"), tmp_path)
    b = write_harbor_task(_make_task("b"), tmp_path)
    assert a.name != b.name
    UUID(a.name)
    UUID(b.name)
