"""Tests for the kraken command surface and the harvest stage.

These cover the parts that decide something: where the knowledge root is, which
merged pull requests count as performance candidates, what a scrape can derive
deterministically, and which records the emitter will reject as incomplete.
"""

from __future__ import annotations

import json

import pytest

from repo2rlenv.github import PullRequestSummary
from repo2rlenv.kraken import ROOT_MARKERS, find_root, harness_dir
from repo2rlenv.pipelines import _perf_runtime_harvest as H


def _make_root(tmp_path):
    """A directory that looks like a kraken knowledge root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "PARAMETERS.md").write_text("# params\n")
    for d in ("seed", "memory", "audit"):
        (tmp_path / d).mkdir()
    return tmp_path


def _pr(number=1, title="", body="", files=None, draft=False):
    return PullRequestSummary(
        number=number,
        title=title,
        body=body,
        state="MERGED",
        merged_at="2026-01-01T00:00:00Z",
        base_ref="main",
        base_sha="a" * 40,
        head_sha="b" * 40,
        is_draft=draft,
        url=f"https://github.com/o/n/pull/{number}",
        changed_files=files if files is not None else ["src/mod.py"],
    )


# --- root discovery ----------------------------------------------------------


def test_find_root_walks_up_from_a_subdirectory(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.delenv("KRAKEN_ROOT", raising=False)
    assert find_root(deep) == root


def test_find_root_prefers_an_explicit_env_var(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("KRAKEN_ROOT", str(root))
    assert find_root(other) == root


def test_find_root_rejects_an_env_var_that_is_not_a_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KRAKEN_ROOT", str(tmp_path))
    with pytest.raises(SystemExit, match="does not look like a kraken tree"):
        find_root(tmp_path)


def test_every_marker_is_required(tmp_path):
    """A directory holding only some markers is not a root.

    Asserted against the predicate rather than find_root, because find_root falls
    back to walking up from its own file and would legitimately find the real tree
    this suite runs inside.
    """
    from repo2rlenv.kraken import _is_root

    partial = tmp_path / "partial"
    (partial / "seed").mkdir(parents=True)
    assert not _is_root(partial)
    assert _is_root(_make_root(tmp_path / "full"))


def test_harness_dir_hangs_off_the_root(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("KRAKEN_ROOT", str(root))
    assert harness_dir(root) == root / "kraken-harness"
    assert harness_dir() == root / "kraken-harness"


def test_markers_name_the_instruments_and_the_requirements():
    assert "requirements/PARAMETERS.md" in ROOT_MARKERS
    for instrument in ("seed", "memory", "audit"):
        assert instrument in ROOT_MARKERS


# --- candidate selection -----------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "perf: speed up the parser",
        "Avoid quadratic scan in resolve",
        "Optimize hot path for large graphs",
        "Reduce latency of the encoder",
    ],
)
def test_performance_titles_are_candidates(title):
    ok, cues = H.is_perf_candidate(_pr(title=title))
    assert ok and cues


def test_a_pr_with_no_performance_language_is_not_a_candidate():
    ok, cues = H.is_perf_candidate(_pr(title="Add a changelog entry"))
    assert not ok and cues == []


def test_selection_reads_the_body_as_well_as_the_title():
    ok, _ = H.is_perf_candidate(_pr(title="Refactor", body="this makes it much faster"))
    assert ok


def test_a_pr_touching_only_tests_changed_no_library_path():
    ok, _ = H.is_perf_candidate(
        _pr(title="perf: faster tests", files=["tests/test_a.py", "tests/test_b.py"])
    )
    assert not ok


def test_a_pr_touching_no_python_is_not_a_candidate():
    ok, _ = H.is_perf_candidate(_pr(title="perf: faster build", files=["Makefile"]))
    assert not ok


def test_a_single_cue_inside_build_noise_is_rejected():
    """ "faster CI" is not a repository-level performance task."""
    ok, _ = H.is_perf_candidate(_pr(title="ci: faster workflow", files=["src/m.py"]))
    assert not ok


def test_covering_tests_are_the_test_files_the_pr_touched():
    pr = _pr(files=["src/mod.py", "tests/test_mod.py", "docs/x.md", "pkg/tests/test_deep.py"])
    assert H.covering_tests(pr) == ["pkg/tests/test_deep.py", "tests/test_mod.py"]


def test_covering_tests_is_empty_when_the_pr_names_none():
    assert H.covering_tests(_pr(files=["src/mod.py"])) == []


# --- environment detection ---------------------------------------------------


def test_pyproject_supplies_the_python_version_and_install(tmp_path):
    (tmp_path / "pyproject.toml").write_text('requires-python = ">=3.11"\n')
    spec = H.detect_env(tmp_path)
    assert spec["python_version"] == "3.11"
    assert "pip install" in spec["install_cmd"]


def test_setup_py_alone_still_yields_an_install_command(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup\n")
    assert "pip install" in H.detect_env(tmp_path)["install_cmd"]


def test_a_bare_checkout_falls_back_rather_than_guessing(tmp_path):
    spec = H.detect_env(tmp_path)
    assert spec["python_version"] == "3.11"


# --- workload synthesis boundaries -------------------------------------------


def test_synthesis_returns_none_when_the_model_call_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no model")

    monkeypatch.setattr("repo2rlenv.llm.complete", boom)
    assert H.synthesize_workload("o/n", "surface", ["e"], object()) is None


def test_synthesis_discards_a_reply_with_no_workload_function(monkeypatch):
    class R:
        content = "def setup():\n    pass\n"

    monkeypatch.setattr("repo2rlenv.llm.complete", lambda *a, **k: R())
    assert H.synthesize_workload("o/n", "surface", ["e"], object()) is None


def test_synthesis_strips_a_markdown_fence(monkeypatch):
    class R:
        content = "```python\ndef setup():\n    pass\n\n\ndef workload():\n    pass\n```"

    monkeypatch.setattr("repo2rlenv.llm.complete", lambda *a, **k: R())
    out = H.synthesize_workload("o/n", "surface", ["e"], object())
    assert out is not None
    assert not out.startswith("```") and "def workload" in out


# --- corpus shard writing ----------------------------------------------------


def test_write_jsonl_reports_what_is_still_incomplete(tmp_path):
    complete = H.Candidate(
        record={
            "instance_id": "o__n-1",
            "covering_tests": ["t.py"],
            "test_cmd": "pytest t.py",
            "workload": "def workload(): pass",
        },
        reasons=["perf"],
        missing=[],
    )
    incomplete = H.Candidate(
        record={"instance_id": "o__n-2", "covering_tests": [], "test_cmd": None, "workload": None},
        reasons=["perf"],
        missing=["covering_tests", "test_cmd", "workload"],
    )

    shard = tmp_path / "o__n.jsonl"
    report = H.write_jsonl([complete, incomplete], shard)

    assert report["written"] == 2
    assert report["complete"] == 1
    assert report["incomplete"] == 1
    assert report["missing_counts"]["workload"] == 1
    rows = [json.loads(line) for line in shard.read_text().splitlines()]
    assert [r["instance_id"] for r in rows] == ["o__n-1", "o__n-2"]


def test_write_jsonl_appends_rather_than_truncating(tmp_path):
    shard = tmp_path / "o__n.jsonl"
    c = H.Candidate(record={"instance_id": "x"}, reasons=[], missing=[])
    H.write_jsonl([c], shard)
    H.write_jsonl([c], shard)
    assert len(shard.read_text().strip().splitlines()) == 2
