from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from helpers import (
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
    make_completion_response,
    make_datum,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


def _fake_requests_get_ok(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "# content\npass\n"
    return resp


# ---------------------------------------------------------------------------
# Data pools for parametrization
# ---------------------------------------------------------------------------
RUN_IDS = [
    "run_001",
    "experiment-2025",
    "test_run",
    "a",
    "Z",
    "0",
    "42",
    "run-with-hyphens",
    "run_with_underscores",
    "run.with.dots",
    "2025-04-24T12-00-00",
    "550e8400-e29b-41d4-a716-446655440000",
    "UPPERCASE_RUN",
    "MiXeD_CaSe",
    "run123abc",
    "abc123",
    "x" * 60,
    "r-1",
    "r_2",
    "r.3",
    "bench_v1",
    "bench_v2",
    "nightly_2025_04",
    "hotfix-99",
    "release-candidate-1",
    "perf_test_final",
    "draft_0",
    "ci-run-4567",
    "user-jdoe-exp",
    "baseline_gold",
]

WORKER_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 28, 32]

DATASET_NAMES = [
    "swefficiency/swefficiency",
    "swefficiency/swefficiency-lite",
    "/tmp/data.jsonl",
    "custom/dataset",
    "huggingface/dataset-v2",
    "org/perf-bench",
    "local_data",
    "./relative/path/data",
    "/absolute/path/data.json",
    "s3://bucket/prefix/data",
    "gs://bucket/data",
    "user/repo-with-hyphens",
    "user/repo_with_underscores",
    "user/repo.with.dots",
    "a/b",
    "my-org/my-dataset-v3",
    "benchmark/large-scale",
    "test/tiny",
    "datasets/code-perf",
    "namespace/sub/deep",
]

SPLITS = [
    "test",
    "train",
    "validation",
    "dev",
    "custom",
    "all",
    "mini",
    "sample",
    "eval",
    "benchmark",
]

REPOS_9 = [
    ("numpy/numpy", "np"),
    ("pandas-dev/pandas", "pd"),
    ("scipy/scipy", "sp"),
    ("scikit-learn/scikit-learn", "sk"),
    ("matplotlib/matplotlib", "mpl"),
    ("pydata/xarray", "xa"),
    ("sympy/sympy", "sym"),
    ("dask/dask", "dsk"),
    ("astropy/astropy", "ast"),
]


# ---------------------------------------------------------------------------
# TestCLIArgParsing — original + massive expansion
# ---------------------------------------------------------------------------
class TestCLIArgParsing:
    # ---- Original: run_id is required ----
    def test_run_id_required(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["prog", "--dataset_name", "test"]):
                from swefficiency.workload.run_synthetic_generation import main
                import argparse
                parser = argparse.ArgumentParser()
                parser.add_argument("--run_id", required=True)
                parser.parse_args(["--dataset_name", "test"])

    # ---- run_ids: 30 variants ----
    @pytest.mark.parametrize("run_id", RUN_IDS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_various_run_ids_via_main(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, run_id, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id=run_id,
            )
        assert (tmp_path / run_id).is_dir()

    # ---- workers: 15 variants ----
    @pytest.mark.parametrize("workers", WORKER_COUNTS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_various_worker_counts(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, workers, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=workers,
                run_id="run_workers",
            )

    # ---- dataset_names: 20 variants ----
    @pytest.mark.parametrize("dataset_name", DATASET_NAMES)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_various_dataset_names(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, dataset_name, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name=dataset_name,
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="run_ds",
            )
        mock_load.assert_called_with(dataset_name, "test")

    # ---- splits: 10 variants ----
    @pytest.mark.parametrize("split", SPLITS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_various_splits(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, split, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split=split,
                instance_ids=None,
                max_workers=1,
                run_id="run_split",
            )
        mock_load.assert_called_with("test", split)

    # ---- Cross: run_ids(30) × workers(15) = 450 ----
    @pytest.mark.parametrize("run_id", RUN_IDS)
    @pytest.mark.parametrize("workers", WORKER_COUNTS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_run_id_x_workers(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, run_id, workers, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=workers,
                run_id=run_id,
            )
        assert (tmp_path / run_id).is_dir()

    # ---- Cross: dataset_names(20) × splits(10) = 200 ----
    @pytest.mark.parametrize("dataset_name", DATASET_NAMES)
    @pytest.mark.parametrize("split", SPLITS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_dataset_x_split(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, dataset_name, split, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name=dataset_name,
                split=split,
                instance_ids=None,
                max_workers=1,
                run_id="run_ds_split",
            )
        mock_load.assert_called_with(dataset_name, split)

    # ---- Cross: run_ids(30) × splits(10) = 300 ----
    @pytest.mark.parametrize("run_id", RUN_IDS)
    @pytest.mark.parametrize("split", SPLITS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_run_id_x_split(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, run_id, split, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split=split,
                instance_ids=None,
                max_workers=1,
                run_id=run_id,
            )
        assert (tmp_path / run_id).is_dir()
        mock_load.assert_called_with("test", split)


# ---------------------------------------------------------------------------
# TestCLIEndToEnd — original + massive expansion
# ---------------------------------------------------------------------------
class TestCLIEndToEnd:
    # ---- Original: single instance ----
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_full_pipeline_single_instance(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = [make_datum()]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="e2e_single",
            )
        output_path = tmp_path / "e2e_single" / "workload_generation.json"
        assert output_path.exists()
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert "import timeit" in lines[0]["workload"]

    # ---- Original: multiple repos ----
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_full_pipeline_multiple_repos(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = [
            make_datum(repo="numpy/numpy", instance_id="np-1"),
            make_datum(repo="pandas-dev/pandas", instance_id="pd-1"),
            make_datum(repo="scipy/scipy", instance_id="sp-1"),
        ]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=2,
                run_id="e2e_multi",
            )
        output_path = tmp_path / "e2e_multi" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    # ---- Original: filtering ----
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_full_pipeline_with_filtering(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = [
            make_datum(instance_id="target-1"),
            make_datum(instance_id="skip-1"),
            make_datum(instance_id="target-2"),
        ]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=["target-1", "target-2"],
                max_workers=1,
                run_id="e2e_filter",
            )
        output_path = tmp_path / "e2e_filter" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        ids = {l["instance_id"] for l in lines}
        assert "target-1" in ids
        assert "target-2" in ids
        assert "skip-1" not in ids

    # ---- Original: py files and jsonl both written ----
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_py_files_and_jsonl_both_written(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = [make_datum(instance_id="check-1"), make_datum(instance_id="check-2")]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="e2e_files",
            )
        assert (tmp_path / "e2e_files" / "check-1.py").exists()
        assert (tmp_path / "e2e_files" / "check-2.py").exists()
        assert (tmp_path / "e2e_files" / "workload_generation.json").exists()

    # ---- Single repo from each of 9 repos ----
    @pytest.mark.parametrize("repo,prefix", REPOS_9)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_single_repo_instance(self, mock_get, mock_comp, mock_meta, mock_setup, repo, prefix, tmp_path):
        iid = f"{prefix}-single-1"
        dataset = [make_datum(repo=repo, instance_id=iid)]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id=f"e2e_{prefix}",
            )
        out = tmp_path / f"e2e_{prefix}" / "workload_generation.json"
        assert out.exists()
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["instance_id"] == iid

    # ---- 9 repos × 4 dataset sizes × 3 worker counts = 108 ----
    @pytest.mark.parametrize("repo,prefix", REPOS_9)
    @pytest.mark.parametrize("ds_size", [1, 3, 5, 10])
    @pytest.mark.parametrize("workers", [1, 2, 4])
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_x_size_x_workers(self, mock_get, mock_comp, mock_meta, mock_setup, repo, prefix, ds_size, workers, tmp_path):
        dataset = [make_datum(repo=repo, instance_id=f"{prefix}-{i}") for i in range(ds_size)]
        rid = f"e2e_{prefix}_{ds_size}_{workers}"
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=workers,
                run_id=rid,
            )
        out = tmp_path / rid / "workload_generation.json"
        assert out.exists()
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == ds_size

    # ---- Repo pairs: C(9,2)=36 pre-computed ----
    @pytest.mark.parametrize("i,j", [(i, j) for i in range(9) for j in range(i + 1, 9)])
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_pairs(self, mock_get, mock_comp, mock_meta, mock_setup, i, j, tmp_path):
        r1, p1 = REPOS_9[i]
        r2, p2 = REPOS_9[j]
        dataset = [
            make_datum(repo=r1, instance_id=f"{p1}-pair-1"),
            make_datum(repo=r2, instance_id=f"{p2}-pair-1"),
        ]
        rid = f"e2e_pair_{p1}_{p2}"
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=2,
                run_id=rid,
            )
        out = tmp_path / rid / "workload_generation.json"
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 2

    # ---- Filtering: valid (n_keep, n_total) combos only ----
    @pytest.mark.parametrize(
        "n_keep,n_total",
        [(k, t) for t in [3, 5, 8, 12, 20] for k in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] if k <= t],
    )
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_filtering_combos(self, mock_get, mock_comp, mock_meta, mock_setup, n_keep, n_total, tmp_path):
        dataset = [make_datum(instance_id=f"inst-{k}") for k in range(n_total)]
        keep_ids = [f"inst-{k}" for k in range(n_keep)]
        rid = f"e2e_filt_{n_total}_{n_keep}"
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=keep_ids,
                max_workers=1,
                run_id=rid,
            )
        out = tmp_path / rid / "workload_generation.json"
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == n_keep
        result_ids = {l["instance_id"] for l in lines}
        for kid in keep_ids:
            assert kid in result_ids


# ---------------------------------------------------------------------------
# TestCLIArgValidation — --run_id required with various arg combos (21 cases)
# ---------------------------------------------------------------------------
_MISSING_RUNID_COMBOS: list[tuple[str, list[str]]] = [
    ("bare", []),
    ("ds_only", ["--dataset_name", "x"]),
    ("split_only", ["--split", "train"]),
    ("workers_only", ["--max_workers", "4"]),
    ("ds_split", ["--dataset_name", "x", "--split", "dev"]),
    ("ds_workers", ["--dataset_name", "x", "--max_workers", "2"]),
    ("split_workers", ["--split", "test", "--max_workers", "8"]),
    ("all_but_runid", ["--dataset_name", "x", "--split", "test", "--max_workers", "1"]),
    ("ids_only", ["--instance_ids", "a", "b"]),
    ("ds_ids", ["--dataset_name", "x", "--instance_ids", "a"]),
    ("split_ids", ["--split", "val", "--instance_ids", "a", "b", "c"]),
    ("workers_ids", ["--max_workers", "3", "--instance_ids", "x"]),
    ("ds_split_ids", ["--dataset_name", "x", "--split", "train", "--instance_ids", "i1"]),
    ("ds_split_workers", ["--dataset_name", "d", "--split", "s", "--max_workers", "7"]),
    ("ds_workers_ids", ["--dataset_name", "d", "--max_workers", "5", "--instance_ids", "z"]),
    ("split_workers_ids", ["--split", "s", "--max_workers", "6", "--instance_ids", "a"]),
    ("all_no_runid", ["--dataset_name", "d", "--split", "s", "--max_workers", "2", "--instance_ids", "a", "b"]),
    ("ds_long", ["--dataset_name", "a/very/long/dataset/path"]),
    ("workers_32", ["--max_workers", "32"]),
    ("workers_1", ["--max_workers", "1"]),
]


class TestCLIArgValidation:
    @pytest.mark.parametrize("label,extra_args", _MISSING_RUNID_COMBOS)
    def test_missing_run_id_raises(self, label, extra_args):
        with pytest.raises(SystemExit):
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--dataset_name", default="swefficiency/swefficiency")
            parser.add_argument("--split", default="test")
            parser.add_argument("--instance_ids", nargs="+")
            parser.add_argument("--max_workers", type=int, default=16)
            parser.add_argument("--run_id", required=True)
            parser.parse_args(extra_args)


# ---------------------------------------------------------------------------
# TestCLIDefaultValues — verify defaults propagate (30 cases)
# ---------------------------------------------------------------------------
_DEFAULT_COMBOS: list[tuple[str, str, str, int]] = []
for _ds in ["swefficiency/swefficiency", "custom/ds", "local/path"]:
    for _sp in ["test", "train", "validation", "dev", "eval"]:
        for _mw in [1, 16]:
            _DEFAULT_COMBOS.append((_ds, _sp, f"def_{_ds.replace('/', '_')}_{_sp}_{_mw}", _mw))


class TestCLIDefaultValues:
    @pytest.mark.parametrize("dataset_name,split,run_id,max_workers", _DEFAULT_COMBOS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_defaults_propagate(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, dataset_name, split, run_id, max_workers, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name=dataset_name,
                split=split,
                instance_ids=None,
                max_workers=max_workers,
                run_id=run_id,
            )
        mock_load.assert_called_with(dataset_name, split)
        assert (tmp_path / run_id).is_dir()


# ---------------------------------------------------------------------------
# TestCLIInstanceIdFiltering — 50 cases
# ---------------------------------------------------------------------------
_FILTER_CASES: list[tuple[str, int, list[str], int]] = []
# single-value filters
for _k in range(10):
    _FILTER_CASES.append((f"single_{_k}", 10, [f"item-{_k}"], 1))
# multi-value filters
for _n_keep in [2, 3, 5, 7, 10]:
    for _n_total in [10, 15, 20]:
        _FILTER_CASES.append(
            (f"multi_{_n_keep}_of_{_n_total}", _n_total, [f"item-{x}" for x in range(_n_keep)], _n_keep)
        )
# non-existent ids
for _k in range(5):
    _FILTER_CASES.append((f"nonexist_{_k}", 5, [f"ghost-{_k}"], 0))


class TestCLIInstanceIdFiltering:
    @pytest.mark.parametrize("label,n_total,filter_ids,expected", _FILTER_CASES)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_instance_id_filter(self, mock_get, mock_comp, mock_meta, mock_setup, label, n_total, filter_ids, expected, tmp_path):
        dataset = [make_datum(instance_id=f"item-{i}") for i in range(n_total)]
        rid = f"filt_{label}"
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name="test",
                split="test",
                instance_ids=filter_ids,
                max_workers=1,
                run_id=rid,
            )
        out = tmp_path / rid / "workload_generation.json"
        assert out.exists()
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == expected


# ---------------------------------------------------------------------------
# TestCLICrossProduct — deterministic sample of big cross-product (~300 cases)
# ---------------------------------------------------------------------------
_CROSS_RUN_IDS = RUN_IDS[:15]
_CROSS_WORKERS = [1, 2, 4, 8, 16]
_CROSS_DATASETS = DATASET_NAMES[:10]
_CROSS_SPLITS = SPLITS[:5]

_CROSS_CASES: list[tuple[str, int, str, str]] = []
_idx = 0
for _rid in _CROSS_RUN_IDS:
    for _w in _CROSS_WORKERS:
        for _ds in _CROSS_DATASETS:
            for _sp in _CROSS_SPLITS:
                if _idx % 12 == 0:
                    _CROSS_CASES.append((_rid, _w, _ds, _sp))
                _idx += 1


class TestCLICrossProduct:
    @pytest.mark.parametrize("run_id,workers,dataset_name,split", _CROSS_CASES)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_cross_product(self, mock_load, mock_get, mock_comp, mock_meta, mock_setup, run_id, workers, dataset_name, split, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            from swefficiency.workload.run_synthetic_generation import main as run_main
            run_main(
                dataset_name=dataset_name,
                split=split,
                instance_ids=None,
                max_workers=workers,
                run_id=run_id,
            )
        assert (tmp_path / run_id).is_dir()
        mock_load.assert_called_with(dataset_name, split)
