from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from helpers import (
    SAMPLE_CODE_BLOCK,
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
    SAMPLE_LLM_RESPONSE_NO_BLOCK,
    SAMPLE_PATCH,
    make_completion_response,
    make_datum,
    main,
    worker_function,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


def _fake_requests_get_ok(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = f"# content of {url}\npass\n"
    return resp


def _make_dataset(n: int = 3, repo: str = "numpy/numpy") -> list[dict[str, Any]]:
    return [
        make_datum(
            instance_id=f"{repo.replace('/', '__')}-{i}",
            repo=repo,
            base_commit=f"{'a' * 38}{i:02d}",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Repo pool used by multi-repo and cross-product tests
# ---------------------------------------------------------------------------
ALL_REPOS = [
    "numpy/numpy",
    "pandas-dev/pandas",
    "scipy/scipy",
    "scikit-learn/scikit-learn",
    "matplotlib/matplotlib",
    "pydata/xarray",
    "sympy/sympy",
    "dask/dask",
    "astropy/astropy",
]

# ---------------------------------------------------------------------------
# Helper: run main with standard mocks
# ---------------------------------------------------------------------------
def _run_main(
    tmp_path,
    dataset,
    run_id="run",
    dataset_name="test",
    split="test",
    instance_ids=None,
    max_workers=1,
    completion_rv=None,
    completion_se=None,
):
    """Run main() with the standard set of mocks; returns output_path."""
    if instance_ids is None:
        instance_ids = []
    comp_kwargs = {}
    if completion_se is not None:
        comp_kwargs["side_effect"] = completion_se
    else:
        comp_kwargs["return_value"] = (
            completion_rv
            if completion_rv is not None
            else make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)
        )
    with (
        patch(f"{MODULE}.setup_helicone"),
        patch(f"{MODULE}.helicone_metadata", return_value={}),
        patch(f"{MODULE}.completion", **comp_kwargs),
        patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
        patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
    ):
        main(
            dataset_name=dataset_name,
            split=split,
            instance_ids=instance_ids,
            max_workers=max_workers,
            run_id=run_id,
        )
    return tmp_path / run_id / "workload_generation.json"


# ===================================================================
# 1. TestMainBasicFlow — 4 tests (original)
# ===================================================================
class TestMainBasicFlow:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_creates_output_file(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(2)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="test_run",
            )
        output_path = tmp_path / "test_run" / "workload_generation.json"
        assert output_path.exists()

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_has_correct_count(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(5)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="test_run",
            )
        output_path = tmp_path / "test_run" / "workload_generation.json"
        lines = [l for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 5

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_lines_are_valid_json(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(3)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="test_run",
            )
        output_path = tmp_path / "test_run" / "workload_generation.json"
        for line in output_path.read_text().splitlines():
            if line.strip():
                parsed = json.loads(line)
                assert "instance_id" in parsed
                assert "run_id" in parsed
                assert "workload" in parsed

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_setup_helicone_called(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(1)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="run1",
            )
        mock_setup.assert_called_once()


# ===================================================================
# 2. TestMainInstanceFiltering — original 4 + parametrized ~25 = 29
# ===================================================================
class TestMainInstanceFiltering:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_filter_by_instance_ids(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(5)
        target_ids = [dataset[0]["instance_id"], dataset[2]["instance_id"]]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=target_ids,
                max_workers=1,
                run_id="run_filter",
            )
        output_path = tmp_path / "run_filter" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        result_ids = {r["instance_id"] for r in lines}
        assert result_ids == set(target_ids)

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_instance_ids_processes_all(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(4)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="run_all",
            )
        output_path = tmp_path / "run_all" / "workload_generation.json"
        lines = [l for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 4

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_instance_ids_processes_all(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(3)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="run_none",
            )
        output_path = tmp_path / "run_none" / "workload_generation.json"
        lines = [l for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_filter_single_id(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(10)
        target = [dataset[5]["instance_id"]]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=target,
                max_workers=1,
                run_id="run_single",
            )
        output_path = tmp_path / "run_single" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["instance_id"] == target[0]

    # --- parametrized filter: pick filter_count items from dataset of ds_size ---
    @pytest.mark.parametrize(
        "ds_size,filter_count",
        [
            (ds, fc)
            for ds in [5, 10, 20, 50]
            for fc in [1, 2, 3, 5, 10]
            if fc <= ds
        ],
    )
    def test_filter_various_sizes(self, ds_size, filter_count, tmp_path):
        dataset = _make_dataset(ds_size)
        target_ids = [dataset[i]["instance_id"] for i in range(filter_count)]
        out = _run_main(tmp_path, dataset, run_id=f"filt_{ds_size}_{filter_count}", instance_ids=target_ids)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == filter_count
        assert {r["instance_id"] for r in lines} == set(target_ids)

    # --- edge: filter with non-existent IDs returns nothing ---
    def test_filter_nonexistent_ids(self, tmp_path):
        dataset = _make_dataset(5)
        out = _run_main(tmp_path, dataset, run_id="filt_noexist", instance_ids=["DOES_NOT_EXIST_0", "DOES_NOT_EXIST_1"])
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 0

    # --- edge: filter with duplicate IDs ---
    def test_filter_duplicate_ids(self, tmp_path):
        dataset = _make_dataset(5)
        dup_id = dataset[0]["instance_id"]
        out = _run_main(tmp_path, dataset, run_id="filt_dup", instance_ids=[dup_id, dup_id])
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        # The source code filters with `in`, so duplicates in instance_ids don't duplicate output
        assert len(lines) == 1

    # --- edge: filter with ALL IDs = same as no filter ---
    @pytest.mark.parametrize("ds_size", [1, 2, 5, 10, 20])
    def test_filter_all_ids(self, ds_size, tmp_path):
        dataset = _make_dataset(ds_size)
        all_ids = [d["instance_id"] for d in dataset]
        out = _run_main(tmp_path, dataset, run_id=f"filt_all_{ds_size}", instance_ids=all_ids)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == ds_size


# ===================================================================
# 3. TestMainMultiWorker — parametrized cross-product = 96 + 1 = 97
# ===================================================================
_MW_WORKERS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 32]
_MW_COUNTS = [1, 2, 3, 5, 8, 10, 15, 20]


class TestMainMultiWorker:
    @pytest.mark.parametrize(
        "workers,count",
        [(w, c) for w in _MW_WORKERS for c in _MW_COUNTS],
    )
    def test_workers_x_counts(self, workers, count, tmp_path):
        dataset = _make_dataset(count)
        out = _run_main(tmp_path, dataset, run_id=f"mw_{workers}_{count}", max_workers=workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_more_workers_than_instances(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(2)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=16,
                run_id="run_many_workers",
            )
        output_path = tmp_path / "run_many_workers" / "workload_generation.json"
        lines = [l for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2


# ===================================================================
# 4. TestMainDirectoryCreation — 2 original + parametrized 50 = 52
# ===================================================================
_DIR_RUN_IDS = [
    "simple", "with_underscore", "CamelCase", "run-dash",
    "run.dot", "r123", "UPPER", "lower", "MixCase99", "x",
]
_DIR_COUNTS = [1, 2, 3, 5, 10]


class TestMainDirectoryCreation:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_creates_output_dir(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(1)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="new_dir_run",
            )
        assert (tmp_path / "new_dir_run").is_dir()

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_per_instance_files_created(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(3)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="file_check_run",
            )
        for datum in dataset:
            py_file = tmp_path / "file_check_run" / f"{datum['instance_id']}.py"
            assert py_file.exists()

    @pytest.mark.parametrize(
        "run_id,count",
        [(rid, c) for rid in _DIR_RUN_IDS for c in _DIR_COUNTS],
    )
    def test_dir_and_files_parametrized(self, run_id, count, tmp_path):
        dataset = _make_dataset(count)
        _run_main(tmp_path, dataset, run_id=run_id)
        assert (tmp_path / run_id).is_dir()
        for datum in dataset:
            assert (tmp_path / run_id / f"{datum['instance_id']}.py").exists()


# ===================================================================
# 5. TestMainDatasetLoading — splits(5) × names(10) = 50 + empty = 51
# ===================================================================
_SPLITS = ["test", "train", "validation", "dev", "custom_split"]
_DATASET_NAMES = [
    "swefficiency/swefficiency",
    "swefficiency/swefficiency-lite",
    "/tmp/data.jsonl",
    "custom/dataset",
    "s3://bucket/data",
    "gs://bucket/data",
    "http://example.com/data",
    "local.jsonl",
    "../data.jsonl",
    "/abs/path.json",
]


class TestMainDatasetLoading:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_passes_dataset_name_and_split(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]) as mock_load,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="custom/dataset",
                split="train",
                instance_ids=[],
                max_workers=1,
                run_id="run_ds",
            )
        mock_load.assert_called_once_with("custom/dataset", "train")

    @pytest.mark.parametrize(
        "split,ds_name",
        [(s, n) for s in _SPLITS for n in _DATASET_NAMES],
    )
    def test_split_x_dataset_name(self, split, ds_name, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]) as mock_load,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name=ds_name,
                split=split,
                instance_ids=[],
                max_workers=1,
                run_id="run_ds_param",
            )
        mock_load.assert_called_once_with(ds_name, split)

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_dataset(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="empty_run",
            )
        output_path = tmp_path / "empty_run" / "workload_generation.json"
        assert output_path.exists()
        content = output_path.read_text().strip()
        assert content == ""


# ===================================================================
# 6. TestMainMixedResults — patterns(6) × sizes(10) = 60
# ===================================================================
_PATTERN_NAMES = [
    "all_block",
    "all_no_block",
    "alternating",
    "first_only",
    "last_only",
    "even_block",
]


def _build_response_pattern(name: str, size: int):
    """Return a list of completion responses for a given pattern."""
    block = make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)
    no_block = make_completion_response(SAMPLE_LLM_RESPONSE_NO_BLOCK)
    if name == "all_block":
        return [block] * size
    if name == "all_no_block":
        return [no_block] * size
    if name == "alternating":
        return [block if i % 2 == 0 else no_block for i in range(size)]
    if name == "first_only":
        return [block] + [no_block] * (size - 1)
    if name == "last_only":
        return [no_block] * (size - 1) + [block]
    if name == "even_block":
        return [block if i % 2 == 0 else no_block for i in range(size)]
    return [block] * size


class TestMainMixedResults:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_mix_of_code_block_and_no_block(self, mock_get, mock_meta, mock_setup, tmp_path):
        dataset = _make_dataset(3)
        responses = [
            make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
            make_completion_response(SAMPLE_LLM_RESPONSE_NO_BLOCK),
            make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
        ]
        call_idx = [0]
        def side_effect(**kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            return responses[idx % len(responses)]

        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.completion", side_effect=side_effect),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="mixed_run",
            )
        output_path = tmp_path / "mixed_run" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        has_code = [l for l in lines if "import timeit" in l["workload"]]
        has_raw = [l for l in lines if "cannot generate" in l["workload"].lower()]
        assert len(has_code) >= 1

    @pytest.mark.parametrize(
        "pattern,size",
        [(p, s) for p in _PATTERN_NAMES for s in range(1, 11)],
    )
    def test_response_patterns(self, pattern, size, tmp_path):
        dataset = _make_dataset(size)
        responses = _build_response_pattern(pattern, size)
        call_idx = [0]

        def _se(**kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            return responses[idx % len(responses)]

        out = _run_main(
            tmp_path, dataset, run_id=f"mix_{pattern}_{size}", completion_se=_se
        )
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == size


# ===================================================================
# 7. TestMainMultipleRepos — single(9) + pairs(36) + triples(84) = 129
# ===================================================================
_SINGLE_REPOS = [(r,) for r in ALL_REPOS]
_PAIR_REPOS = list(combinations(ALL_REPOS, 2))
_TRIPLE_REPOS = list(combinations(ALL_REPOS, 3))


class TestMainMultipleRepos:
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_instances_from_different_repos(self, mock_get, mock_comp, mock_meta, mock_setup, tmp_path):
        dataset = [
            make_datum(repo="numpy/numpy", instance_id="numpy__numpy-1"),
            make_datum(repo="pandas-dev/pandas", instance_id="pandas-dev__pandas-1"),
            make_datum(repo="scipy/scipy", instance_id="scipy__scipy-1"),
        ]
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="multi_repo",
            )
        output_path = tmp_path / "multi_repo" / "workload_generation.json"
        lines = [json.loads(l) for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        ids = {l["instance_id"] for l in lines}
        assert "numpy__numpy-1" in ids
        assert "pandas-dev__pandas-1" in ids
        assert "scipy__scipy-1" in ids

    @pytest.mark.parametrize("repos", _SINGLE_REPOS, ids=[r[0].replace("/", "_") for r in _SINGLE_REPOS])
    def test_single_repo(self, repos, tmp_path):
        dataset = [
            make_datum(
                repo=repos[0],
                instance_id=f"{repos[0].replace('/', '__')}-0",
            )
        ]
        safe = repos[0].replace("/", "_")
        out = _run_main(tmp_path, dataset, run_id=f"sr_{safe}")
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    @pytest.mark.parametrize(
        "repos",
        _PAIR_REPOS,
        ids=[f"{a.split('/')[1]}_{b.split('/')[1]}" for a, b in _PAIR_REPOS],
    )
    def test_pair_repos(self, repos, tmp_path):
        dataset = [
            make_datum(repo=r, instance_id=f"{r.replace('/', '__')}-0")
            for r in repos
        ]
        safe = "_".join(r.split("/")[1] for r in repos)
        out = _run_main(tmp_path, dataset, run_id=f"pr_{safe}")
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == len(repos)
        result_ids = {ln["instance_id"] for ln in lines}
        for r in repos:
            assert f"{r.replace('/', '__')}-0" in result_ids

    @pytest.mark.parametrize(
        "repos",
        _TRIPLE_REPOS,
        ids=[f"{a.split('/')[1]}_{b.split('/')[1]}_{c.split('/')[1]}" for a, b, c in _TRIPLE_REPOS],
    )
    def test_triple_repos(self, repos, tmp_path):
        dataset = [
            make_datum(repo=r, instance_id=f"{r.replace('/', '__')}-0")
            for r in repos
        ]
        safe = "_".join(r.split("/")[1] for r in repos)
        out = _run_main(tmp_path, dataset, run_id=f"tr_{safe}")
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == len(repos)


# ===================================================================
# 8. TestMainScaling — expanded INSTANCE_COUNTS = 19 cases
# ===================================================================
INSTANCE_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100]


class TestMainScaling:
    @pytest.mark.parametrize("count", INSTANCE_COUNTS)
    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_various_dataset_sizes(self, mock_get, mock_comp, mock_meta, mock_setup, count, tmp_path):
        dataset = _make_dataset(count)
        with (
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id=f"scale_{count}",
            )
        output_path = tmp_path / f"scale_{count}" / "workload_generation.json"
        lines = [l for l in output_path.read_text().splitlines() if l.strip()]
        assert len(lines) == count


# ===================================================================
# 9. TestMainOutputFormat — counts(10) × repos(9) = 90 + 10 encoding = 100
# ===================================================================
_FMT_COUNTS = [1, 2, 3, 4, 5, 6, 8, 10, 15, 20]


class TestMainOutputFormat:
    @pytest.mark.parametrize(
        "count,repo",
        [(c, r) for c in _FMT_COUNTS for r in ALL_REPOS],
    )
    def test_jsonl_keys_and_types(self, count, repo, tmp_path):
        dataset = _make_dataset(count, repo=repo)
        safe = repo.replace("/", "_")
        out = _run_main(tmp_path, dataset, run_id=f"fmt_{safe}_{count}")
        raw = out.read_text()
        lines = [l for l in raw.splitlines() if l.strip()]
        assert len(lines) == count
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj["instance_id"], str)
            assert isinstance(obj["run_id"], str)
            assert isinstance(obj["workload"], str)
            assert obj["run_id"] == f"fmt_{safe}_{count}"

    @pytest.mark.parametrize("count", _FMT_COUNTS)
    def test_utf8_encoding(self, count, tmp_path):
        dataset = _make_dataset(count)
        out = _run_main(tmp_path, dataset, run_id=f"enc_{count}")
        raw = out.read_bytes()
        text = raw.decode("utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) == count


# ===================================================================
# 10. TestMainIdempotency — 20 cases
# ===================================================================
_IDEM_COUNTS = [1, 2, 3, 5, 10]
_IDEM_WORKERS = [1, 2, 4, 8]


class TestMainIdempotency:
    @pytest.mark.parametrize(
        "count,workers",
        [(c, w) for c in _IDEM_COUNTS for w in _IDEM_WORKERS],
    )
    def test_run_twice_overwrites(self, count, workers, tmp_path):
        dataset = _make_dataset(count)
        run_id = f"idem_{count}_{workers}"
        _run_main(tmp_path, dataset, run_id=run_id, max_workers=workers)
        _run_main(tmp_path, dataset, run_id=run_id, max_workers=workers)
        out = tmp_path / run_id / "workload_generation.json"
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count


# ===================================================================
# 11. TestMainEdgeCases — ~100 cases
# ===================================================================
_EDGE_COUNTS = [1, 2, 3, 5, 10, 20]


class TestMainEdgeCases:
    # empty dataset × various workers
    @pytest.mark.parametrize("workers", [1, 2, 4, 8, 16, 32])
    def test_empty_dataset_various_workers(self, workers, tmp_path):
        out = _run_main(tmp_path, [], run_id=f"edge_empty_{workers}", max_workers=workers)
        assert out.exists()
        assert out.read_text().strip() == ""

    # single instance × various workers
    @pytest.mark.parametrize("workers", [1, 2, 4, 8, 16, 32])
    def test_single_instance_various_workers(self, workers, tmp_path):
        dataset = _make_dataset(1)
        out = _run_main(tmp_path, dataset, run_id=f"edge_single_{workers}", max_workers=workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    # unicode instance_ids
    @pytest.mark.parametrize(
        "uid",
        [
            "numpy__numpy-café-0",
            "numpy__numpy-über-1",
            "numpy__numpy-日本語-2",
            "numpy__numpy-émoji-3",
            "numpy__numpy-Ω-4",
        ],
    )
    def test_unicode_instance_ids(self, uid, tmp_path):
        dataset = [make_datum(instance_id=uid)]
        out = _run_main(tmp_path, dataset, run_id="edge_unicode")
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["instance_id"] == uid

    # various run_id patterns
    @pytest.mark.parametrize(
        "run_id",
        [
            "a", "ab", "abc", "run_123", "RUN", "run-with-dashes",
            "run.with.dots", "run_with_underscores", "123numeric",
            "ALLCAPS", "mixedCase", "x" * 50, "x" * 100, "x" * 200,
        ],
    )
    def test_various_run_ids(self, run_id, tmp_path):
        dataset = _make_dataset(2)
        out = _run_main(tmp_path, dataset, run_id=run_id)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        assert all(r["run_id"] == run_id for r in lines)

    # count × run_id combos
    @pytest.mark.parametrize(
        "count,rid",
        [(c, f"edge_{c}_{i}") for c in _EDGE_COUNTS for i in range(5)],
    )
    def test_count_x_run_id(self, count, rid, tmp_path):
        dataset = _make_dataset(count)
        out = _run_main(tmp_path, dataset, run_id=rid)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count

    @pytest.mark.parametrize(
        "count,repo",
        [(c, r) for c in [1, 2, 5, 10] for r in ALL_REPOS],
    )
    def test_count_x_repo_edge(self, count, repo, tmp_path):
        dataset = _make_dataset(count, repo=repo)
        safe = repo.replace("/", "_")
        out = _run_main(tmp_path, dataset, run_id=f"edge_repo_{safe}_{count}")
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count
        for ln in lines:
            assert ln["instance_id"].startswith(repo.replace("/", "__"))

    @pytest.mark.parametrize("count", [1, 2, 3, 5, 10, 20, 30, 50])
    def test_all_results_have_workload(self, count, tmp_path):
        dataset = _make_dataset(count)
        out = _run_main(tmp_path, dataset, run_id=f"edge_wl_{count}")
        for line in out.read_text().splitlines():
            if line.strip():
                obj = json.loads(line)
                assert "workload" in obj
                assert len(obj["workload"]) > 0

    @pytest.mark.parametrize(
        "workers,count",
        [(w, c) for w in [1, 4, 16] for c in [1, 5]],
    )
    def test_output_dir_exists_after_run(self, workers, count, tmp_path):
        dataset = _make_dataset(count)
        rid = f"edge_dir_{workers}_{count}"
        _run_main(tmp_path, dataset, run_id=rid, max_workers=workers)
        assert (tmp_path / rid).is_dir()
        assert (tmp_path / rid / "workload_generation.json").exists()

    @pytest.mark.parametrize("split", _SPLITS)
    def test_empty_dataset_with_various_splits(self, split, tmp_path):
        rid = f"edge_empty_split_{split}"
        out = _run_main(tmp_path, [], run_id=rid, split=split)
        assert out.exists()
        assert out.read_text().strip() == ""


# ===================================================================
# 12. TestMainHeliconeSetup — counts(10) × workers(5) = 50
# ===================================================================
_HELI_COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 50]
_HELI_WORKERS = [1, 2, 4, 8, 16]


class TestMainHeliconeSetup:
    @pytest.mark.parametrize(
        "count,workers",
        [(c, w) for c in _HELI_COUNTS for w in _HELI_WORKERS],
    )
    def test_setup_called_once(self, count, workers, tmp_path):
        dataset = _make_dataset(count)
        with (
            patch(f"{MODULE}.setup_helicone") as mock_setup,
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=workers,
                run_id=f"heli_{count}_{workers}",
            )
        mock_setup.assert_called_once()


# ===================================================================
# 13. TestMainCrossProduct — repos(9) × workers(4) × counts(6) × splits(4) = 864
# ===================================================================
_CP_WORKERS = [1, 2, 4, 8]
_CP_COUNTS = [1, 2, 3, 5, 8, 10, 15, 20]
_CP_SPLITS = ["test", "train", "validation", "dev"]


class TestMainCrossProduct:
    @pytest.mark.parametrize(
        "repo,workers,count,split",
        [
            (r, w, c, s)
            for r in ALL_REPOS
            for w in _CP_WORKERS
            for c in _CP_COUNTS
            for s in _CP_SPLITS
        ],
    )
    def test_cross_product(self, repo, workers, count, split, tmp_path):
        dataset = _make_dataset(count, repo=repo)
        safe = repo.replace("/", "_")
        rid = f"cp_{safe}_{workers}_{count}_{split}"
        out = _run_main(
            tmp_path,
            dataset,
            run_id=rid,
            dataset_name=f"ds_{safe}",
            split=split,
            max_workers=workers,
        )
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count


# ===================================================================
# 14. TestMainFilterCrossProduct — ds_sizes(6) × strategies(5) × filter_fracs(5) = 150
# ===================================================================
_FCP_DS_SIZES = [5, 10, 15, 20, 30, 50]
_FCP_FRACS = [0.1, 0.25, 0.5, 0.75, 1.0]


class TestMainFilterCrossProduct:
    @pytest.mark.parametrize(
        "ds_size,frac",
        [(ds, f) for ds in _FCP_DS_SIZES for f in _FCP_FRACS],
    )
    def test_filter_fraction(self, ds_size, frac, tmp_path):
        dataset = _make_dataset(ds_size)
        n_filter = max(1, int(ds_size * frac))
        target_ids = [dataset[i]["instance_id"] for i in range(n_filter)]
        rid = f"fcf_{ds_size}_{int(frac * 100)}"
        out = _run_main(tmp_path, dataset, run_id=rid, instance_ids=target_ids)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == n_filter
        assert {r["instance_id"] for r in lines} == set(target_ids)

    @pytest.mark.parametrize(
        "ds_size,workers",
        [(ds, w) for ds in _FCP_DS_SIZES for w in [1, 2, 4, 8]],
    )
    def test_filter_half_various_workers(self, ds_size, workers, tmp_path):
        dataset = _make_dataset(ds_size)
        n_filter = ds_size // 2 or 1
        target_ids = [dataset[i]["instance_id"] for i in range(n_filter)]
        rid = f"fch_{ds_size}_{workers}"
        out = _run_main(tmp_path, dataset, run_id=rid, instance_ids=target_ids, max_workers=workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == n_filter

    @pytest.mark.parametrize(
        "ds_size,n_pick",
        [
            (ds, pick)
            for ds in _FCP_DS_SIZES
            for pick in [1, 2, 3, 5]
            if pick <= ds
        ],
    )
    def test_filter_pick_n(self, ds_size, n_pick, tmp_path):
        dataset = _make_dataset(ds_size)
        target_ids = [dataset[i]["instance_id"] for i in range(n_pick)]
        rid = f"fcp_{ds_size}_{n_pick}"
        out = _run_main(tmp_path, dataset, run_id=rid, instance_ids=target_ids)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == n_pick

    @pytest.mark.parametrize(
        "ds_size,frac,workers",
        [
            (ds, f, w)
            for ds in [10, 20, 30, 50]
            for f in [0.2, 0.5, 0.8]
            for w in [1, 2, 4]
        ],
    )
    def test_filter_frac_workers(self, ds_size, frac, workers, tmp_path):
        dataset = _make_dataset(ds_size)
        n_filter = max(1, int(ds_size * frac))
        target_ids = [dataset[i]["instance_id"] for i in range(n_filter)]
        rid = f"fcfw_{ds_size}_{int(frac * 100)}_{workers}"
        out = _run_main(tmp_path, dataset, run_id=rid, instance_ids=target_ids, max_workers=workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == n_filter
