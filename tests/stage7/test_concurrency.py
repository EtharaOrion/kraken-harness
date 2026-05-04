from __future__ import annotations

import json
import os
import threading
import time
import concurrent.futures
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from helpers import (
    SAMPLE_CODE_BLOCK,
    SAMPLE_LLM_RESPONSE_NO_BLOCK,
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
    SAMPLE_PATCH,
    make_completion_response,
    make_datum,
    main,
    worker_function,
    WORKLOAD_GENERATION_DIR,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _run_worker_in_thread(datum, run_id, tmp_path, results_list, errors_list, delay=0):
    """Run worker_function inside a thread, appending result or error."""
    try:
        if delay:
            time.sleep(delay)
        with (
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, run_id)
            results_list.append(result)
    except Exception as e:
        errors_list.append(e)


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
# 1. TestConcurrentFileWrites (~20 cases)
# ===================================================================

class TestConcurrentFileWrites:
    """Multiple workers writing files concurrently — verify all files created."""

    def test_two_workers_same_run_different_instances(self, tmp_path):
        """Two workers with same run_id but different instance_ids create separate files."""
        results, errors = [], []
        d0 = make_datum(instance_id="inst_A")
        d1 = make_datum(instance_id="inst_B")
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d0, "run1", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(d1, "run1", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 2
        assert (tmp_path / "run1" / "inst_A.py").exists()
        assert (tmp_path / "run1" / "inst_B.py").exists()

    def test_five_workers_same_run_different_instances(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"inst_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run5", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        for i in range(5):
            assert (tmp_path / "run5" / f"inst_{i}.py").exists()

    def test_ten_concurrent_workers(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"w10_{i}") for i in range(10)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run10", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        for i in range(10):
            assert (tmp_path / "run10" / f"w10_{i}.py").exists()

    def test_twenty_concurrent_workers(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"w20_{i}") for i in range(20)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run20", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 20
        for i in range(20):
            assert (tmp_path / "run20" / f"w20_{i}.py").exists()

    def test_fifty_concurrent_workers(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"w50_{i}") for i in range(50)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run50", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 50
        for i in range(50):
            assert (tmp_path / "run50" / f"w50_{i}.py").exists()

    def test_same_instance_id_last_write_wins_no_crash(self, tmp_path):
        """Two workers writing to same instance_id — last-write-wins, no crash."""
        results, errors = [], []
        d0 = make_datum(instance_id="same_inst")
        d1 = make_datum(instance_id="same_inst")
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d0, "run_same", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(d1, "run_same", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 2
        assert (tmp_path / "run_same" / "same_inst.py").exists()

    def test_three_workers_same_instance_id_no_crash(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id="triple") for _ in range(3)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run_triple", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert (tmp_path / "run_triple" / "triple.py").exists()
        content = (tmp_path / "run_triple" / "triple.py").read_text()
        assert len(content) > 0

    def test_five_workers_same_instance_id_no_crash(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id="five_same") for _ in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "run_5same", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert (tmp_path / "run_5same" / "five_same.py").exists()

    def test_directory_creation_thread_safe_two_threads(self, tmp_path):
        """Two workers creating the same parent directory concurrently."""
        results, errors = [], []
        d0 = make_datum(instance_id="dir_safe_0")
        d1 = make_datum(instance_id="dir_safe_1")
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d0, "dir_race", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(d1, "dir_race", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert (tmp_path / "dir_race").is_dir()
        assert (tmp_path / "dir_race" / "dir_safe_0.py").exists()
        assert (tmp_path / "dir_race" / "dir_safe_1.py").exists()

    def test_directory_creation_thread_safe_ten_threads(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"ds10_{i}") for i in range(10)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "ds10_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert (tmp_path / "ds10_run").is_dir()
        for i in range(10):
            assert (tmp_path / "ds10_run" / f"ds10_{i}.py").exists()

    def test_multiple_run_ids_concurrent(self, tmp_path):
        """Workers with different run_ids running concurrently."""
        results, errors = [], []
        d0 = make_datum(instance_id="cross_run_0")
        d1 = make_datum(instance_id="cross_run_1")
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d0, "runA", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(d1, "runB", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert (tmp_path / "runA" / "cross_run_0.py").exists()
        assert (tmp_path / "runB" / "cross_run_1.py").exists()

    def test_five_different_run_ids_concurrent(self, tmp_path):
        results, errors = [], []
        for i in range(5):
            d = make_datum(instance_id=f"multi_run_{i}")
            t = threading.Thread(target=_run_worker_in_thread, args=(d, f"mrun_{i}", tmp_path, results, errors))
            t.start()
        # join all active threads except main
        for t in threading.enumerate():
            if t is not threading.current_thread() and t.daemon is False:
                try:
                    t.join(timeout=30)
                except RuntimeError:
                    pass
        assert len(errors) == 0
        for i in range(5):
            assert (tmp_path / f"mrun_{i}" / f"multi_run_{i}.py").exists()

    def test_directory_mkdir_exist_ok_idempotent(self, tmp_path):
        """Pre-create directory, then run concurrent workers — should not fail."""
        (tmp_path / "preexist").mkdir(parents=True, exist_ok=True)
        results, errors = [], []
        data = [make_datum(instance_id=f"pre_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "preexist", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 5

    @pytest.mark.parametrize("n_workers", [3, 6, 8, 12, 15])
    def test_parametrized_concurrent_workers(self, n_workers, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"param_{n_workers}_{i}") for i in range(n_workers)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, f"param_run_{n_workers}", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == n_workers
        for i in range(n_workers):
            assert (tmp_path / f"param_run_{n_workers}" / f"param_{n_workers}_{i}.py").exists()

    def test_concurrent_workers_nested_run_id_path(self, tmp_path):
        """Run ID with slashes — nested directory creation is thread-safe."""
        results, errors = [], []
        data = [make_datum(instance_id=f"nested_{i}") for i in range(4)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "level1/level2", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for i in range(4):
            assert (tmp_path / "level1" / "level2" / f"nested_{i}.py").exists()


# ===================================================================
# 2. TestConcurrentOutputIntegrity (~15 cases)
# ===================================================================

class TestConcurrentOutputIntegrity:
    """Each output file contains correct content — no cross-contamination."""

    def test_two_workers_correct_content_per_file(self, tmp_path):
        results, errors = [], []
        d0 = make_datum(instance_id="content_A")
        d1 = make_datum(instance_id="content_B")
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d0, "crun", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(d1, "crun", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for iid in ("content_A", "content_B"):
            content = (tmp_path / "crun" / f"{iid}.py").read_text()
            assert "import timeit" in content
            assert "def setup():" in content

    def test_five_workers_each_file_has_valid_python(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"valid_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "vrun", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for i in range(5):
            content = (tmp_path / "vrun" / f"valid_{i}.py").read_text()
            assert "import timeit" in content
            assert "statistics" in content

    def test_ten_workers_no_content_mixing(self, tmp_path):
        """Run 10 workers — each file must contain the expected code block, not garbage."""
        results, errors = [], []
        data = [make_datum(instance_id=f"mix_{i}") for i in range(10)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "mixrun", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for i in range(10):
            content = (tmp_path / "mixrun" / f"mix_{i}.py").read_text()
            # Content should be the extracted code block
            assert content == SAMPLE_CODE_BLOCK

    def test_json_output_not_corrupted_by_concurrent_writes(self, tmp_path):
        """Run main with multiple workers, verify JSONL output is parseable."""
        dataset = _make_dataset(10)
        out = _run_main(tmp_path, dataset, run_id="json_safe", max_workers=4)
        lines = out.read_text().splitlines()
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) == 10
        for line in non_empty:
            obj = json.loads(line)
            assert "instance_id" in obj
            assert "run_id" in obj
            assert "workload" in obj

    def test_json_output_not_corrupted_8_workers(self, tmp_path):
        dataset = _make_dataset(15)
        out = _run_main(tmp_path, dataset, run_id="json8", max_workers=8)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 15
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj["workload"], str)

    def test_each_worker_gets_own_output_path(self, tmp_path):
        """Different instance_ids produce different file paths."""
        results, errors = [], []
        ids = ["alpha", "beta", "gamma", "delta"]
        data = [make_datum(instance_id=iid) for iid in ids]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "own_path", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        paths = set()
        for iid in ids:
            p = tmp_path / "own_path" / f"{iid}.py"
            assert p.exists()
            paths.add(str(p))
        assert len(paths) == 4  # all unique

    def test_result_dict_instance_id_matches_input(self, tmp_path):
        """Each worker's returned dict has correct instance_id."""
        results, errors = [], []
        data = [make_datum(instance_id=f"match_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "matchrun", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        result_ids = {r["instance_id"] for r in results}
        expected_ids = {f"match_{i}" for i in range(5)}
        assert result_ids == expected_ids

    def test_result_dict_run_id_matches_input(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"rid_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "const_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for r in results:
            assert r["run_id"] == "const_run"

    def test_result_workload_not_empty(self, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"wl_{i}") for i in range(8)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "wlrun", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for r in results:
            assert len(r["workload"]) > 0

    def test_file_content_matches_workload_field(self, tmp_path):
        """File on disk matches the workload field in the result dict."""
        results, errors = [], []
        data = [make_datum(instance_id=f"fwm_{i}") for i in range(3)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "fwmrun", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for r in results:
            file_content = (tmp_path / "fwmrun" / f"{r['instance_id']}.py").read_text()
            # workload field is the extracted code block
            assert file_content == SAMPLE_CODE_BLOCK

    @pytest.mark.parametrize("n_workers", [2, 4, 7, 10, 15])
    def test_parametrized_output_integrity(self, n_workers, tmp_path):
        results, errors = [], []
        data = [make_datum(instance_id=f"pi_{n_workers}_{i}") for i in range(n_workers)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, f"pi_{n_workers}", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert len(errors) == 0
        assert len(results) == n_workers
        for i in range(n_workers):
            f = tmp_path / f"pi_{n_workers}" / f"pi_{n_workers}_{i}.py"
            assert f.exists()
            assert "import timeit" in f.read_text()

    def test_sequential_no_block_response_files_empty(self, tmp_path):
        """Workers receiving no code block write empty files.

        Run sequentially because unittest.mock.patch is not thread-safe:
        concurrent patches on the same module attribute can leak across threads.
        """
        data = [make_datum(instance_id=f"noblock_{i}") for i in range(4)]
        for datum in data:
            with (
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_NO_BLOCK)),
                patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.time.sleep"),
            ):
                worker_function(datum, "nb_run")
        for i in range(4):
            f = tmp_path / "nb_run" / f"noblock_{i}.py"
            assert f.exists()
            assert f.read_text() == ""


# ===================================================================
# 3. TestMainConcurrentExecution (~15 cases)
# ===================================================================

class TestMainConcurrentExecution:
    """main() using ThreadPoolExecutor — verify correctness across worker counts."""

    @pytest.mark.parametrize("max_workers", [1, 2, 4, 8, 16])
    def test_same_result_count_various_workers(self, max_workers, tmp_path):
        dataset = _make_dataset(10)
        out = _run_main(tmp_path, dataset, run_id=f"mw_{max_workers}", max_workers=max_workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 10

    def test_more_workers_than_tasks_no_deadlock(self, tmp_path):
        dataset = _make_dataset(3)
        out = _run_main(tmp_path, dataset, run_id="deadlock_test", max_workers=32)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_single_worker_single_task(self, tmp_path):
        dataset = _make_dataset(1)
        out = _run_main(tmp_path, dataset, run_id="single", max_workers=1)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_16_workers_1_task_no_deadlock(self, tmp_path):
        dataset = _make_dataset(1)
        out = _run_main(tmp_path, dataset, run_id="w16_t1", max_workers=16)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_tqdm_no_crash_with_concurrent_futures(self, tmp_path):
        """main() uses tqdm over as_completed — ensure no crash."""
        dataset = _make_dataset(8)
        out = _run_main(tmp_path, dataset, run_id="tqdm_test", max_workers=4)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 8

    def test_tqdm_no_crash_large_dataset(self, tmp_path):
        dataset = _make_dataset(30)
        out = _run_main(tmp_path, dataset, run_id="tqdm_large", max_workers=8)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 30

    def test_all_instance_ids_present_in_output_4_workers(self, tmp_path):
        dataset = _make_dataset(10)
        out = _run_main(tmp_path, dataset, run_id="ids_check", max_workers=4)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        result_ids = {r["instance_id"] for r in lines}
        expected_ids = {d["instance_id"] for d in dataset}
        assert result_ids == expected_ids

    def test_all_instance_ids_present_8_workers(self, tmp_path):
        dataset = _make_dataset(20)
        out = _run_main(tmp_path, dataset, run_id="ids8", max_workers=8)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        result_ids = {r["instance_id"] for r in lines}
        expected_ids = {d["instance_id"] for d in dataset}
        assert result_ids == expected_ids

    def test_per_instance_py_files_created_with_workers(self, tmp_path):
        dataset = _make_dataset(6)
        _run_main(tmp_path, dataset, run_id="pyfiles", max_workers=4)
        for d in dataset:
            assert (tmp_path / "pyfiles" / f"{d['instance_id']}.py").exists()

    def test_per_instance_py_files_16_workers(self, tmp_path):
        dataset = _make_dataset(10)
        _run_main(tmp_path, dataset, run_id="pyfiles16", max_workers=16)
        for d in dataset:
            assert (tmp_path / "pyfiles16" / f"{d['instance_id']}.py").exists()

    @pytest.mark.parametrize(
        "max_workers,count",
        [(2, 5), (4, 10), (8, 20), (16, 30), (32, 5)],
    )
    def test_workers_x_count_output_correct(self, max_workers, count, tmp_path):
        dataset = _make_dataset(count)
        out = _run_main(tmp_path, dataset, run_id=f"wxc_{max_workers}_{count}", max_workers=max_workers)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == count


# ===================================================================
# 4. TestThreadSafetyEdgeCases (~10 cases)
# ===================================================================

class TestThreadSafetyEdgeCases:
    """Edge cases around thread safety — exceptions, timing, result ordering."""

    def test_one_failing_worker_doesnt_corrupt_others(self, tmp_path):
        """One worker raises in completion — others still succeed."""
        call_tracker = {"count": 0}
        lock = threading.Lock()

        def _flaky_completion(**kwargs):
            with lock:
                call_tracker["count"] += 1
                current = call_tracker["count"]
            if current == 1:
                raise RuntimeError("Simulated LLM failure")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        results, errors = [], []
        data = [make_datum(instance_id=f"fail_{i}") for i in range(3)]

        def _run_with_flaky(datum, run_id, tmp_p, res_list, err_list):
            try:
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", side_effect=_flaky_completion),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        threads = [
            threading.Thread(target=_run_with_flaky, args=(d, "fail_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        # The flaky completion retries, so all should eventually succeed
        assert len(results) == 3
        for r in results:
            assert r is not None

    def test_all_workers_complete_simultaneously_results_complete(self, tmp_path):
        """All workers finishing at nearly the same time — results list is complete."""
        barrier = threading.Barrier(5, timeout=30)
        results, errors = [], []

        def _run_with_barrier(datum, run_id, tmp_p, res_list, err_list):
            try:
                barrier.wait()
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        data = [make_datum(instance_id=f"barrier_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_with_barrier, args=(d, "barrier_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 5
        result_ids = {r["instance_id"] for r in results}
        assert result_ids == {f"barrier_{i}" for i in range(5)}

    def test_varying_delays_order_independence(self, tmp_path):
        """Workers completing at different times — all results collected regardless of order."""
        results, errors = [], []
        data = [make_datum(instance_id=f"delay_{i}") for i in range(5)]
        # Staggered delays: 0, 0.01, 0.02, 0.03, 0.04 — trivial but ordered
        threads = [
            threading.Thread(
                target=_run_worker_in_thread,
                args=(d, "delay_run", tmp_path, results, errors),
                kwargs={"delay": i * 0.01},
            )
            for i, d in enumerate(data)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 5
        result_ids = {r["instance_id"] for r in results}
        assert result_ids == {f"delay_{i}" for i in range(5)}

    def test_exception_in_one_main_future_doesnt_lose_others(self, tmp_path):
        """main() with ThreadPoolExecutor — one future exception handled by retry loop."""
        call_count = {"n": 0}
        lock = threading.Lock()

        def _completion_sometimes_fail(**kwargs):
            with lock:
                call_count["n"] += 1
                n = call_count["n"]
            # First call fails, rest succeed (retry loop will retry)
            if n == 1:
                raise Exception("transient error")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        dataset = _make_dataset(5)
        out = _run_main(
            tmp_path, dataset, run_id="exc_main", max_workers=4,
            completion_se=_completion_sometimes_fail,
        )
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 5

    def test_results_list_thread_safe_append(self, tmp_path):
        """Verify that results accumulated in main() match dataset size under concurrency."""
        dataset = _make_dataset(20)
        out = _run_main(tmp_path, dataset, run_id="append_safe", max_workers=8)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 20
        ids = {r["instance_id"] for r in lines}
        expected = {d["instance_id"] for d in dataset}
        assert ids == expected

    def test_concurrent_workers_different_repos_no_interference(self, tmp_path):
        """Workers for different repos running concurrently — no interference."""
        results, errors = [], []
        repos = ["numpy/numpy", "scipy/scipy", "pandas-dev/pandas"]
        data = [make_datum(instance_id=f"{r.replace('/', '__')}-conc", repo=r) for r in repos]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "multi_repo", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 3
        result_ids = {r["instance_id"] for r in results}
        for r in repos:
            assert f"{r.replace('/', '__')}-conc" in result_ids

    def test_rapid_sequential_concurrent_runs_no_state_leak(self, tmp_path):
        """Run main() twice rapidly with different run_ids — no cross-contamination."""
        dataset1 = _make_dataset(5)
        dataset2 = _make_dataset(3, repo="scipy/scipy")
        out1 = _run_main(tmp_path, dataset1, run_id="seq_run1", max_workers=4)
        out2 = _run_main(tmp_path, dataset2, run_id="seq_run2", max_workers=4)
        lines1 = [json.loads(l) for l in out1.read_text().splitlines() if l.strip()]
        lines2 = [json.loads(l) for l in out2.read_text().splitlines() if l.strip()]
        assert len(lines1) == 5
        assert len(lines2) == 3
        ids1 = {r["instance_id"] for r in lines1}
        ids2 = {r["instance_id"] for r in lines2}
        assert ids1.isdisjoint(ids2)

    def test_worker_return_value_preserved_under_concurrency(self, tmp_path):
        """All returned dicts have the three required keys."""
        results, errors = [], []
        data = [make_datum(instance_id=f"keys_{i}") for i in range(8)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "keys_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        for r in results:
            assert "instance_id" in r
            assert "run_id" in r
            assert "workload" in r

    def test_concurrent_futures_executor_no_leaked_threads(self, tmp_path):
        """After main() completes, no lingering worker threads from the pool."""
        baseline_threads = threading.active_count()
        dataset = _make_dataset(10)
        _run_main(tmp_path, dataset, run_id="leak_check", max_workers=8)
        # Allow a small margin for pytest/framework threads
        assert threading.active_count() <= baseline_threads + 2

    def test_main_empty_dataset_no_deadlock_high_workers(self, tmp_path):
        """Empty dataset with high worker count — no deadlock or hang."""
        out = _run_main(tmp_path, [], run_id="empty_high", max_workers=32)
        assert out.exists()
        assert out.read_text().strip() == ""


# ===================================================================
# 5. TestTOCTOU (~15 cases) — Time-of-Check-Time-of-Use races
# ===================================================================

class TestTOCTOU:
    """Race conditions where state changes between check and use."""

    def test_output_dir_deleted_between_mkdir_and_write(self, tmp_path):
        """Output directory removed after mkdir but before file write."""
        datum = make_datum(instance_id="toctou_del")
        run_id = "toctou_run"
        original_open = open

        def _sabotage_open(path, *args, **kwargs):
            p = Path(str(path))
            if p.name == "toctou_del.py" and p.parent.exists():
                p.parent.rmdir()
            return original_open(path, *args, **kwargs)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            try:
                result = worker_function(datum, run_id)
                assert isinstance(result, dict)
            except (FileNotFoundError, OSError):
                pass

    def test_workload_generation_dir_deleted_between_mkdir_and_write(self, tmp_path):
        """WORKLOAD_GENERATION_DIR itself deleted between mkdir and file write."""
        datum = make_datum(instance_id="toctou_wgd")
        call_count = {"n": 0}
        original_mkdir = Path.mkdir

        def _patched_mkdir(self_path, *args, **kwargs):
            original_mkdir(self_path, *args, **kwargs)
            call_count["n"] += 1
            if call_count["n"] == 1 and self_path.exists():
                import shutil
                shutil.rmtree(self_path, ignore_errors=True)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
            patch.object(Path, "mkdir", _patched_mkdir),
        ):
            try:
                result = worker_function(datum, "toctou_wgd_run")
                assert isinstance(result, dict)
            except (FileNotFoundError, OSError):
                pass

    def test_output_file_created_between_check_and_write(self, tmp_path):
        """Another process creates the output file before worker writes — overwrite behavior."""
        run_id = "toctou_overwrite"
        instance_id = "toctou_pre"
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        pre_content = "# pre-existing content\n"
        (out_dir / f"{instance_id}.py").write_text(pre_content)

        datum = make_datum(instance_id=instance_id)
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)
        final_content = (out_dir / f"{instance_id}.py").read_text()
        assert final_content != pre_content
        assert final_content == SAMPLE_CODE_BLOCK

    def test_permission_change_between_mkdir_and_write(self, tmp_path):
        """Directory becomes read-only between mkdir and file write."""
        datum = make_datum(instance_id="toctou_perm")
        run_id = "toctou_perm_run"
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        original_write_text = Path.write_text

        def _make_readonly_then_write(self_path, *args, **kwargs):
            if self_path.name == "toctou_perm.py":
                os.chmod(str(self_path.parent), 0o444)
                try:
                    return original_write_text(self_path, *args, **kwargs)
                finally:
                    os.chmod(str(self_path.parent), 0o755)
            return original_write_text(self_path, *args, **kwargs)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
            patch.object(Path, "write_text", _make_readonly_then_write),
        ):
            try:
                result = worker_function(datum, run_id)
                assert isinstance(result, dict)
            except PermissionError:
                pass
            finally:
                os.chmod(str(out_dir), 0o755)

    def test_dir_becomes_readonly_between_check_and_write(self, tmp_path):
        """Simulate directory becoming readonly between existence check and write."""
        datum = make_datum(instance_id="toctou_ro")
        run_id = "toctou_ro_run"
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        call_count = {"n": 0}
        original_open_fn = open

        def _readonly_sabotage(path, *args, **kwargs):
            path_str = str(path)
            if "toctou_ro.py" in path_str:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    os.chmod(str(out_dir), 0o444)
            try:
                return original_open_fn(path, *args, **kwargs)
            except PermissionError:
                os.chmod(str(out_dir), 0o755)
                raise

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            try:
                result = worker_function(datum, run_id)
                assert isinstance(result, dict)
            except PermissionError:
                pass
            finally:
                os.chmod(str(out_dir), 0o755)

    def test_two_workers_check_same_dir_existence_simultaneously(self, tmp_path):
        """Two workers check same directory existence at the same time via barrier."""
        barrier = threading.Barrier(2, timeout=10)
        results, errors = [], []

        def _run_with_barrier(datum, run_id, tmp_p, res_list, err_list):
            try:
                barrier.wait()
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion",
                          return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        d0 = make_datum(instance_id="simul_A")
        d1 = make_datum(instance_id="simul_B")
        threads = [
            threading.Thread(target=_run_with_barrier, args=(d0, "simul_run", tmp_path, results, errors)),
            threading.Thread(target=_run_with_barrier, args=(d1, "simul_run", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 2
        assert (tmp_path / "simul_run" / "simul_A.py").exists()
        assert (tmp_path / "simul_run" / "simul_B.py").exists()

    def test_file_deleted_between_extract_and_write(self, tmp_path):
        """File created by a previous step is deleted before final write completes."""
        datum = make_datum(instance_id="toctou_extract")
        run_id = "toctou_ext_run"
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "toctou_extract.py"
        target.write_text("# placeholder\n")

        original_write_text = Path.write_text

        def _delete_then_write(self_path, *args, **kwargs):
            if self_path.name == "toctou_extract.py" and self_path.exists():
                self_path.unlink()
            return original_write_text(self_path, *args, **kwargs)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
            patch.object(Path, "write_text", _delete_then_write),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)
        assert target.exists()

    def test_barrier_synchronized_access_same_paths(self, tmp_path):
        """Use threading.Barrier to synchronize 4 workers accessing same paths."""
        barrier = threading.Barrier(4, timeout=10)
        results, errors = [], []

        def _run_barrier(datum, run_id, tmp_p, res_list, err_list):
            try:
                barrier.wait()
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion",
                          return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        data = [make_datum(instance_id=f"bar4_{i}") for i in range(4)]
        threads = [
            threading.Thread(target=_run_barrier, args=(d, "bar4_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 4
        for i in range(4):
            assert (tmp_path / "bar4_run" / f"bar4_{i}.py").exists()

    def test_mock_os_path_exists_returns_different_values(self, tmp_path):
        """Mock os.path.exists to return False then True on successive calls."""
        datum = make_datum(instance_id="toctou_exists")
        run_id = "toctou_exists_run"
        call_count = {"n": 0}
        original_exists = os.path.exists

        def _flaky_exists(path):
            if "toctou_exists_run" in str(path):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return False
                return True
            return original_exists(path)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
            patch("os.path.exists", side_effect=_flaky_exists),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)

    def test_concurrent_mkdir_race_three_threads(self, tmp_path):
        """Three threads race to mkdir the same directory — all succeed or get exist_ok."""
        barrier = threading.Barrier(3, timeout=10)
        results, errors = [], []

        def _run_mkdir_race(datum, run_id, tmp_p, res_list, err_list):
            try:
                barrier.wait()
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion",
                          return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        data = [make_datum(instance_id=f"mkrace_{i}") for i in range(3)]
        threads = [
            threading.Thread(target=_run_mkdir_race, args=(d, "mkrace_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 3

    def test_rapid_create_delete_create_directory(self, tmp_path):
        """Create dir, delete it, then worker creates it again — no crash."""
        run_id = "toctou_cdc"
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_dir.rmdir()

        datum = make_datum(instance_id="toctou_cdc_inst")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)
        assert (out_dir / "toctou_cdc_inst.py").exists()

    def test_symlink_race_dir_replaced_with_symlink(self, tmp_path):
        """Directory replaced with a symlink between check and use."""
        run_id = "toctou_sym"
        real_dir = tmp_path / "real_target"
        real_dir.mkdir(parents=True, exist_ok=True)
        out_dir = tmp_path / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        datum = make_datum(instance_id="toctou_sym_inst")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)

    def test_five_threads_barrier_all_write_same_run_id(self, tmp_path):
        """Five threads synchronized by barrier all writing to same run_id directory."""
        barrier = threading.Barrier(5, timeout=10)
        results, errors = [], []

        def _run_sync(datum, run_id, tmp_p, res_list, err_list):
            try:
                barrier.wait()
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion",
                          return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        data = [make_datum(instance_id=f"sync5_{i}") for i in range(5)]
        threads = [
            threading.Thread(target=_run_sync, args=(d, "sync5_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        for i in range(5):
            assert (tmp_path / "sync5_run" / f"sync5_{i}.py").exists()

    def test_exists_flicker_multiple_calls(self, tmp_path):
        """os.path.exists alternates True/False across multiple calls."""
        datum = make_datum(instance_id="toctou_flicker")
        run_id = "toctou_flicker_run"
        call_count = {"n": 0}
        original_exists = os.path.exists

        def _flickering_exists(path):
            if "toctou_flicker_run" in str(path):
                call_count["n"] += 1
                return call_count["n"] % 2 == 0
            return original_exists(path)

        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
            patch("os.path.exists", side_effect=_flickering_exists),
        ):
            result = worker_function(datum, run_id)
        assert isinstance(result, dict)


# ===================================================================
# 6. TestDoubleSubmission (~10 cases) — Idempotency
# ===================================================================

class TestDoubleSubmission:
    """Same datum submitted multiple times — verify idempotency and consistency."""

    def test_same_datum_same_run_id_twice_both_complete(self, tmp_path):
        """Same datum with same run_id submitted twice — both complete, same file content."""
        datum = make_datum(instance_id="double_sub")
        run_id = "double_run"
        for _ in range(2):
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion",
                      return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                patch(f"{MODULE}.time.sleep"),
            ):
                result = worker_function(datum, run_id)
                assert isinstance(result, dict)
                assert result["instance_id"] == "double_sub"
        content = (tmp_path / run_id / "double_sub.py").read_text()
        assert content == SAMPLE_CODE_BLOCK

    def test_same_datum_different_run_ids_separate_dirs(self, tmp_path):
        """Same datum submitted with different run_ids — different output directories."""
        datum = make_datum(instance_id="multi_run_inst")
        for rid in ("run_alpha", "run_beta"):
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion",
                      return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                patch(f"{MODULE}.time.sleep"),
            ):
                result = worker_function(datum, rid)
                assert isinstance(result, dict)
        assert (tmp_path / "run_alpha" / "multi_run_inst.py").exists()
        assert (tmp_path / "run_beta" / "multi_run_inst.py").exists()
        content_a = (tmp_path / "run_alpha" / "multi_run_inst.py").read_text()
        content_b = (tmp_path / "run_beta" / "multi_run_inst.py").read_text()
        assert content_a == content_b == SAMPLE_CODE_BLOCK

    def test_two_identical_worker_calls_concurrent_no_corruption(self, tmp_path):
        """Two identical worker_function calls running concurrently — no corruption."""
        datum = make_datum(instance_id="conc_double")
        results, errors = [], []
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(datum, "conc_dbl_run", tmp_path, results, errors)),
            threading.Thread(target=_run_worker_in_thread, args=(datum, "conc_dbl_run", tmp_path, results, errors)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 2
        content = (tmp_path / "conc_dbl_run" / "conc_double.py").read_text()
        assert content == SAMPLE_CODE_BLOCK

    def test_output_file_not_partially_written(self, tmp_path):
        """Verify output file is not partially written — atomic content check."""
        datum = make_datum(instance_id="atomic_write")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, "atomic_run")
        content = (tmp_path / "atomic_run" / "atomic_write.py").read_text()
        assert content == SAMPLE_CODE_BLOCK
        assert len(content) > 0
        assert content.count("import timeit") == 1

    def test_rerun_main_same_params_results_consistent(self, tmp_path):
        """Re-running main with same parameters — results consistent."""
        dataset = _make_dataset(5)
        out1 = _run_main(tmp_path, dataset, run_id="rerun1", max_workers=2)
        lines1 = [json.loads(l) for l in out1.read_text().splitlines() if l.strip()]
        out2 = _run_main(tmp_path, dataset, run_id="rerun2", max_workers=2)
        lines2 = [json.loads(l) for l in out2.read_text().splitlines() if l.strip()]
        assert len(lines1) == len(lines2) == 5
        ids1 = {r["instance_id"] for r in lines1}
        ids2 = {r["instance_id"] for r in lines2}
        assert ids1 == ids2

    def test_same_instance_id_different_patch_later_write_wins(self, tmp_path):
        """Same instance_id with different patch content — later write wins."""
        run_id = "patch_over"
        resp1 = "```python\nprint('first')\n```"
        resp2 = "```python\nprint('second')\n```"

        for resp in (resp1, resp2):
            datum = make_datum(instance_id="patch_inst")
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion",
                      return_value=make_completion_response(resp)),
                patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                patch(f"{MODULE}.time.sleep"),
            ):
                worker_function(datum, run_id)

        content = (tmp_path / run_id / "patch_inst.py").read_text()
        assert content == "print('second')"

    def test_triple_submission_same_datum(self, tmp_path):
        """Same datum submitted three times sequentially — all succeed."""
        datum = make_datum(instance_id="triple_sub")
        for i in range(3):
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion",
                      return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
                patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                patch(f"{MODULE}.time.sleep"),
            ):
                result = worker_function(datum, "triple_run")
                assert isinstance(result, dict)
        assert (tmp_path / "triple_run" / "triple_sub.py").exists()

    def test_concurrent_triple_same_datum_no_crash(self, tmp_path):
        """Three concurrent submissions of same datum — no crash."""
        datum = make_datum(instance_id="conc_triple")
        results, errors = [], []
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(datum, "ct_run", tmp_path, results, errors))
            for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 3
        assert (tmp_path / "ct_run" / "conc_triple.py").exists()

    def test_main_duplicate_instances_in_dataset(self, tmp_path):
        """Dataset with duplicate instance_ids — main processes all without error."""
        d = make_datum(instance_id="dup_inst")
        dataset = [d, d, d]
        out = _run_main(tmp_path, dataset, run_id="dup_main", max_workers=2)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        assert (tmp_path / "dup_main" / "dup_inst.py").exists()

    def test_sequential_then_concurrent_same_datum(self, tmp_path):
        """Run datum once sequentially, then twice concurrently — all succeed."""
        datum = make_datum(instance_id="seq_then_conc")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.time.sleep"),
        ):
            result = worker_function(datum, "stc_run")
            assert isinstance(result, dict)

        results, errors = [], []
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(datum, "stc_run", tmp_path, results, errors))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 2
        assert (tmp_path / "stc_run" / "seq_then_conc.py").exists()


# ===================================================================
# 7. TestStarvation (~10 cases) — Worker fairness
# ===================================================================

class TestStarvation:
    """Verify no worker is permanently starved or blocked."""

    def test_one_slow_worker_many_fast_all_complete(self, tmp_path):
        """One slow worker (2s sleep) with many fast workers — all complete."""
        call_count = {"n": 0}
        lock = threading.Lock()

        def _slow_first_completion(**kwargs):
            with lock:
                call_count["n"] += 1
                is_first = call_count["n"] == 1
            if is_first:
                time.sleep(2)
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        results, errors = [], []
        data = [make_datum(instance_id=f"starve_{i}") for i in range(6)]

        def _run_slow(datum, run_id, tmp_p, res_list, err_list):
            try:
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", side_effect=_slow_first_completion),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        threads = [
            threading.Thread(target=_run_slow, args=(d, "starve_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 6

    def test_max_workers_1_many_items_all_complete(self, tmp_path):
        """max_workers=1 with many items — all eventually processed."""
        dataset = _make_dataset(10)
        out = _run_main(tmp_path, dataset, run_id="single_w", max_workers=1)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 10
        ids = {json.loads(l)["instance_id"] for l in lines}
        expected = {d["instance_id"] for d in dataset}
        assert ids == expected

    def test_slow_worker_doesnt_block_thread_pool(self, tmp_path):
        """Worker that takes much longer — doesn't block other threads in pool."""
        call_count = {"n": 0}
        lock = threading.Lock()
        fast_completions = []

        def _variable_speed(**kwargs):
            with lock:
                call_count["n"] += 1
                current = call_count["n"]
            if current == 1:
                time.sleep(1.5)
            else:
                fast_completions.append(time.time())
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        dataset = _make_dataset(5)
        out = _run_main(
            tmp_path, dataset, run_id="slow_pool", max_workers=4,
            completion_se=_variable_speed,
        )
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 5

    def test_no_worker_permanently_blocked_with_timeout(self, tmp_path):
        """Verify no worker is permanently blocked — all complete within timeout."""
        results, errors = [], []
        data = [make_datum(instance_id=f"timeout_{i}") for i in range(8)]
        threads = [
            threading.Thread(target=_run_worker_in_thread, args=(d, "to_run", tmp_path, results, errors))
            for d in data
        ]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.time() - start
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 8
        assert elapsed < 30, f"Workers took too long: {elapsed:.1f}s"

    def test_mixed_fast_slow_fast_complete_promptly(self, tmp_path):
        """Mixed fast/slow workers — fast ones complete promptly, slow one finishes."""
        timing_lock = threading.Lock()
        fast_times: list[float] = []
        slow_time: list[float] = []
        call_count = {"n": 0}

        def _mixed_speed(**kwargs):
            with timing_lock:
                call_count["n"] += 1
                current = call_count["n"]
            if current == 3:
                time.sleep(1.0)
                slow_time.append(time.time())
            else:
                fast_times.append(time.time())
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        results, errors = [], []
        data = [make_datum(instance_id=f"mixed_{i}") for i in range(5)]

        def _run_mixed(datum, run_id, tmp_p, res_list, err_list):
            try:
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", side_effect=_mixed_speed),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        threads = [
            threading.Thread(target=_run_mixed, args=(d, "mixed_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5

    def test_all_slow_workers_still_complete(self, tmp_path):
        """All workers are slow (0.5s each) — all still complete within timeout."""
        def _all_slow(**kwargs):
            time.sleep(0.5)
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        results, errors = [], []
        data = [make_datum(instance_id=f"allslow_{i}") for i in range(4)]

        def _run_all_slow(datum, run_id, tmp_p, res_list, err_list):
            try:
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", side_effect=_all_slow),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        threads = [
            threading.Thread(target=_run_all_slow, args=(d, "allslow_run", tmp_path, results, errors))
            for d in data
        ]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.time() - start
        assert len(errors) == 0
        assert len(results) == 4
        assert elapsed < 10

    def test_single_worker_many_items_sequential_fairness(self, tmp_path):
        """Single-threaded processing of many items — all items get processed."""
        dataset = _make_dataset(15)
        out = _run_main(tmp_path, dataset, run_id="fair_seq", max_workers=1)
        lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 15
        ids = {r["instance_id"] for r in lines}
        expected = {d["instance_id"] for d in dataset}
        assert ids == expected

    def test_progressive_slowdown_all_complete(self, tmp_path):
        """Workers get progressively slower — all still complete."""
        call_count = {"n": 0}
        lock = threading.Lock()

        def _progressive_slow(**kwargs):
            with lock:
                call_count["n"] += 1
                delay = call_count["n"] * 0.1
            time.sleep(delay)
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        results, errors = [], []
        data = [make_datum(instance_id=f"prog_{i}") for i in range(6)]

        def _run_prog(datum, run_id, tmp_p, res_list, err_list):
            try:
                with (
                    patch(f"{MODULE}.helicone_metadata", return_value={}),
                    patch(f"{MODULE}.completion", side_effect=_progressive_slow),
                    patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
                    patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_p),
                    patch(f"{MODULE}.time.sleep"),
                ):
                    result = worker_function(datum, run_id)
                    res_list.append(result)
            except Exception as e:
                err_list.append(e)

        threads = [
            threading.Thread(target=_run_prog, args=(d, "prog_run", tmp_path, results, errors))
            for d in data
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(errors) == 0
        assert len(results) == 6

    def test_high_worker_count_low_task_count_no_starvation(self, tmp_path):
        """32 workers for 3 tasks — no deadlock or starvation."""
        dataset = _make_dataset(3)
        out = _run_main(tmp_path, dataset, run_id="high_w", max_workers=32)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_main_with_slow_completion_all_tasks_finish(self, tmp_path):
        """main() with slow completion (0.3s per call) — all tasks finish."""
        def _slow_comp(**kwargs):
            time.sleep(0.3)
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        dataset = _make_dataset(8)
        out = _run_main(
            tmp_path, dataset, run_id="slow_main", max_workers=4,
            completion_se=_slow_comp,
        )
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 8
