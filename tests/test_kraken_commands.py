"""Tests for the five kraken commands.

These exercise the command surface itself: which root each stage resolves, what
argument vector reaches Harbor, and whether a stage's call into the next one still
matches that function's signature. A stage that dies on its first line is invisible
to tests of the functions underneath it.
"""

from __future__ import annotations

import json
import sys
from typing import ClassVar

import pytest

from repo2rlenv.kraken import cli


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A directory that satisfies every marker, pointed at by KRAKEN_ROOT."""
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "PARAMETERS.md").write_text("# params\n")
    for d in ("seed", "memory", "audit"):
        (tmp_path / d).mkdir()
    monkeypatch.setenv("KRAKEN_ROOT", str(tmp_path))
    return tmp_path


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["kraken", *argv])
    return cli.main()


# --- import-time independence -------------------------------------------------


def test_the_module_imports_without_a_kraken_tree(monkeypatch):
    """The harness is an installable package and CI checks it out on its own.

    Resolving the root at import time made `import repo2rlenv.kraken.cli` raise
    SystemExit anywhere outside the tree, which no command-level test could reach.
    """
    monkeypatch.delenv("KRAKEN_ROOT", raising=False)
    import importlib

    importlib.reload(cli)
    assert callable(cli.main)


def test_no_kraken_module_resolves_the_root_while_being_imported(monkeypatch):
    """Import must not depend on where the tree is, for every module in the package.

    cli, judge and validate each resolved the root at module scope. On a developer
    machine the harness sits inside the kraken tree, so the upward walk from the
    source file finds a root and every one of them imports fine. CI checks the
    harness out on its own, where the same import aborts collection outright.

    Making find_root refuse catches that wherever the source happens to live, which
    a test that merely unsets KRAKEN_ROOT cannot do.
    """
    import importlib

    import repo2rlenv.kraken as package

    def refuse(*_a, **_k):
        raise AssertionError("the knowledge root was resolved at import time")

    monkeypatch.setattr(package, "find_root", refuse)
    modules = ("cli", "judge", "validate")
    for name in modules:
        monkeypatch.delitem(sys.modules, f"repo2rlenv.kraken.{name}", raising=False)
    try:
        for name in modules:
            importlib.import_module(f"repo2rlenv.kraken.{name}")
    finally:
        # Re-import under the real find_root so later tests get working modules.
        monkeypatch.undo()
        for name in modules:
            sys.modules.pop(f"repo2rlenv.kraken.{name}", None)
            importlib.import_module(f"repo2rlenv.kraken.{name}")


def test_a_command_still_demands_a_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KRAKEN_ROOT", str(tmp_path / "not-a-tree"))
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "status")


# --- status -------------------------------------------------------------------


def test_status_counts_an_empty_tree(root, monkeypatch, capsys):
    assert run_cli(monkeypatch, "status") == 0
    got = json.loads(capsys.readouterr().out)
    assert got["corpus_shards"] == 0
    assert got["corpus_records"] == 0
    assert got["authored_bundles"] == 0
    assert got["harness_stages"] == ["harvest", "author", "run", "grade"]


def test_status_counts_records_bundles_and_trajectories(root, monkeypatch, capsys):
    (root / "harvest").mkdir()
    (root / "harvest" / "a__b.jsonl").write_text('{"instance_id":"x"}\n\n{"instance_id":"y"}\n')
    ds = root / "kraken-dataset"
    (ds / "bundle-one").mkdir(parents=True)
    (ds / "bundle-one" / "task.toml").write_text("[task]\n")
    (ds / "not-a-bundle").mkdir()  # no task.toml
    (root / "trajectories" / "2026-08-03__10-00-00").mkdir(parents=True)

    assert run_cli(monkeypatch, "status") == 0
    got = json.loads(capsys.readouterr().out)
    assert got["corpus_shards"] == 1
    assert got["corpus_records"] == 2, "blank lines are not records"
    assert got["authored_bundles"] == 1, "a directory without task.toml is not a bundle"
    assert got["trajectories"] == 1


# --- run ----------------------------------------------------------------------


def test_run_refuses_when_harbor_is_absent(root, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert run_cli(monkeypatch, "run", "--bundle", "kraken-dataset/x") == 2


def test_run_resolves_a_relative_bundle_against_the_root(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/harbor")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd: _Completed(seen, cmd, cwd))

    assert run_cli(monkeypatch, "run", "--bundle", "kraken-dataset/x") == 0
    assert seen["cmd"][:4] == ["harbor", "run", "-p", str(root / "kraken-dataset" / "x")]
    assert seen["cwd"] == root
    assert "--env" in seen["cmd"] and "docker" in seen["cmd"]
    assert str(root / "trajectories") in seen["cmd"]


def test_run_leaves_an_absolute_bundle_alone(root, monkeypatch, tmp_path):
    seen = {}
    elsewhere = tmp_path / "somewhere" / "bundle"
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/harbor")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd: _Completed(seen, cmd, cwd))

    run_cli(monkeypatch, "run", "--bundle", str(elsewhere))
    assert seen["cmd"][3] == str(elsewhere)


def test_run_passes_attempts_concurrency_and_agent_env_through(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/harbor")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd: _Completed(seen, cmd, cwd))

    run_cli(
        monkeypatch,
        "run",
        "--bundle",
        "b",
        "-k",
        "16",
        "-n",
        "4",
        "--agent-env",
        "ANTHROPIC_BASE_URL=http://host.docker.internal:8765",
        "--agent-env",
        "ANTHROPIC_API_KEY=proxy",
    )
    cmd = seen["cmd"]
    assert cmd[cmd.index("-k") + 1] == "16"
    assert cmd[cmd.index("-n") + 1] == "4"
    assert cmd.count("--agent-env") == 2
    assert "ANTHROPIC_API_KEY=proxy" in cmd


def test_run_omits_the_flags_it_has_no_reason_to_send(root, monkeypatch):
    """A single attempt is Harbor's own default; sending -k 1 would just be noise."""
    seen = {}
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/harbor")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd: _Completed(seen, cmd, cwd))

    run_cli(monkeypatch, "run", "--bundle", "b")
    assert "-k" not in seen["cmd"] and "-n" not in seen["cmd"]
    assert "--agent-env" not in seen["cmd"]


def test_run_returns_harbors_exit_code(root, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/harbor")
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, cwd: _Completed({}, cmd, cwd, code=3))
    assert run_cli(monkeypatch, "run", "--bundle", "b") == 3


class _Completed:
    def __init__(self, sink, cmd, cwd, code=0):
        sink["cmd"], sink["cwd"] = cmd, cwd
        self.returncode = code


# --- grade --------------------------------------------------------------------


def test_grade_calls_the_judge_with_the_arguments_it_accepts(root, monkeypatch, tmp_path):
    """The call site and judge.run must agree.

    grade passed a `root=` keyword the judge never declared, so the stage raised
    TypeError before reading anything. Binding through the real signature is what
    makes that a test failure rather than a runtime surprise.
    """
    from repo2rlenv.kraken import judge

    seen = {}

    def fake_run(*, bundle, logs, seed=17):
        seen.update(bundle=bundle, logs=logs, seed=seed)
        return 0

    monkeypatch.setattr(judge, "run", fake_run)
    assert run_cli(monkeypatch, "grade", "--bundle", "b", "--logs", "l") == 0
    assert str(seen["bundle"]) == "b"
    assert str(seen["logs"]) == "l"


# --- harvest ------------------------------------------------------------------


def test_harvest_splits_a_provider_qualified_model(root, monkeypatch, capsys):
    seen = {}

    def fake_harvest(repo, limit, llm_spec):
        seen["spec"] = llm_spec
        return []

    monkeypatch.setattr("repo2rlenv.pipelines._perf_runtime_harvest.harvest_repo", fake_harvest)
    run_cli(monkeypatch, "harvest", "--repo", "o/n", "--model", "anthropic/claude-opus-4-8")
    assert seen["spec"].provider == "anthropic"
    assert seen["spec"].model == "claude-opus-4-8"


def test_harvest_defaults_a_bare_model_to_anthropic(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "repo2rlenv.pipelines._perf_runtime_harvest.harvest_repo",
        lambda repo, limit, llm_spec: seen.setdefault("spec", llm_spec) and [],
    )
    run_cli(monkeypatch, "harvest", "--repo", "o/n", "--model", "claude-opus-4-8")
    assert seen["spec"].provider == "anthropic"
    assert seen["spec"].model == "claude-opus-4-8"


def test_harvest_without_a_model_synthesizes_nothing(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "repo2rlenv.pipelines._perf_runtime_harvest.harvest_repo",
        lambda repo, limit, llm_spec: seen.setdefault("spec", llm_spec) and [],
    )
    run_cli(monkeypatch, "harvest", "--repo", "o/n")
    assert seen["spec"] is None


def test_harvest_writes_a_shard_per_repo_and_totals_them(root, monkeypatch, capsys):
    from repo2rlenv.pipelines import _perf_runtime_harvest as H

    def fake_harvest(repo, limit, llm_spec):
        if repo == "o/empty":
            return []
        return [
            H.Candidate(record={"instance_id": f"{repo}-1"}, reasons=["perf"], missing=[]),
            H.Candidate(
                record={"instance_id": f"{repo}-2"}, reasons=["perf"], missing=["workload"]
            ),
        ]

    monkeypatch.setattr(H, "harvest_repo", fake_harvest)
    assert run_cli(monkeypatch, "harvest", "--repo", "o/n", "--repo", "o/empty") == 0

    out = capsys.readouterr().out
    got = json.loads(out[: out.index("}") + 1])
    assert got["written"] == 2
    assert got["complete"] == 1 and got["incomplete"] == 1
    assert (root / "harvest" / "o__n.jsonl").exists()
    assert not (root / "harvest" / "o__empty.jsonl").exists()
    assert "Pass --model" in out, "an incomplete record should say how to complete it"


# --- author -------------------------------------------------------------------


def test_author_reports_what_the_pipeline_emitted_and_skipped(root, monkeypatch, capsys):
    from repo2rlenv.pipelines import perf_runtime as P

    class FakeResult:
        candidates, emitted, skipped = 3, 1, 2
        skip_reasons: ClassVar[dict] = {"no_workload": 2}

    class FakePipeline:
        def __init__(self, gen_input, options):
            FakePipeline.opts = options

        def run(self, out):
            FakePipeline.out = out
            return FakeResult()

    monkeypatch.setattr(P, "PerfRuntimePipeline", FakePipeline)
    assert run_cli(monkeypatch, "author", "--registry", "reg.example/x") == 0

    got = json.loads(capsys.readouterr().out)
    assert got["emitted"] == 1 and got["skipped"] == 2
    assert got["skip_reasons"] == {"no_workload": 2}
    assert FakePipeline.out == root / "kraken-dataset"
    assert FakePipeline.opts.corpus == str(root / "harvest")
    assert FakePipeline.opts.registry == "reg.example/x"
