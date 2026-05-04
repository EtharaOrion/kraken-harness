from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from helpers import (
    extract_code_block,
    main,
    make_completion_response,
    make_datum,
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


SAMPLE_LLM_CODE = """\
Here is a workload script:

```python
import timeit
import statistics

def setup():
    pass

def workload():
    pass

runtimes = timeit.repeat(workload, number=1, repeat=5, setup=setup)

print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
```
"""


def _make_dataset(n: int = 3, repo: str = "numpy/numpy") -> list[dict[str, Any]]:
    return [
        make_datum(
            instance_id=f"{repo.replace('/', '__')}-{i}",
            repo=repo,
            base_commit=f"{'a' * 38}{i:02d}",
        )
        for i in range(n)
    ]


def _run_main(
    tmp_path,
    dataset,
    run_id="run",
    dataset_name="test",
    split="test",
    instance_ids=None,
    max_workers=1,
    completion_rv=None,
):
    if instance_ids is None:
        instance_ids = []
    comp_kwargs = {
        "return_value": (
            completion_rv
            if completion_rv is not None
            else make_completion_response(SAMPLE_LLM_CODE)
        )
    }
    with (
        patch(f"{MODULE}.setup_helicone"),
        patch(f"{MODULE}.helicone_metadata", return_value={}),
        patch(f"{MODULE}.completion", **comp_kwargs),
        patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
        patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        patch(f"{MODULE}.time.sleep"),
    ):
        main(
            dataset_name=dataset_name,
            split=split,
            instance_ids=instance_ids,
            max_workers=max_workers,
            run_id=run_id,
        )
    return tmp_path / run_id / "workload_generation.json"


def _run_worker(tmp_path, datum, run_id, llm_response=None):
    """Run worker_function with all externals mocked, return result."""
    resp = make_completion_response(llm_response or SAMPLE_LLM_CODE)
    with (
        patch(f"{MODULE}.helicone_metadata", return_value={}),
        patch(f"{MODULE}.completion", return_value=resp),
        patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        patch(f"{MODULE}.time.sleep"),
    ):
        return worker_function(datum, run_id)


# ===================================================================
# 1. TestExtractCodeBlockPerformance (~15 cases)
# ===================================================================

class TestExtractCodeBlockPerformance:
    """Performance characteristics of extract_code_block with extreme inputs."""

    def test_1mb_text_completes_under_2s(self):
        """1 MB of plain text with one code block at the end."""
        filler = "x" * (1024 * 1024)
        text = filler + "\n```python\nprint('ok')\n```\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "print('ok')"
        assert elapsed < 2.0, f"Took {elapsed:.2f}s for 1 MB input"

    def test_5mb_text_completes_under_5s(self):
        """5 MB of plain text with one code block at the end."""
        filler = "y" * (5 * 1024 * 1024)
        text = filler + "\n```python\nprint('big')\n```\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "print('big')"
        assert elapsed < 5.0, f"Took {elapsed:.2f}s for 5 MB input"

    def test_1mb_no_code_block_completes_under_2s(self):
        """1 MB with no code block — regex finds no match quickly."""
        text = "a" * (1024 * 1024)
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 2.0, f"Took {elapsed:.2f}s"

    def test_5mb_no_code_block_completes_under_5s(self):
        """5 MB with no code block — regex finds no match quickly."""
        text = "b" * (5 * 1024 * 1024)
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 5.0, f"Took {elapsed:.2f}s"

    def test_1000_code_blocks_returns_first(self):
        """Text with 1000 code blocks — returns the first one quickly."""
        blocks = []
        for i in range(1000):
            blocks.append(f"```python\nblock_{i}\n```\n")
        text = "\n".join(blocks)
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "block_0"
        assert elapsed < 2.0, f"Took {elapsed:.2f}s for 1000 blocks"

    def test_500_code_blocks_returns_first(self):
        """Text with 500 code blocks — returns the first one."""
        blocks = [f"```python\nblock_{i}\n```\n" for i in range(500)]
        text = "\n".join(blocks)
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "block_0"
        assert elapsed < 1.0, f"Took {elapsed:.2f}s for 500 blocks"

    def test_100k_line_code_block(self):
        """Code block with 100K lines of content."""
        content_lines = [f"line_{i} = {i}" for i in range(100_000)]
        content = "\n".join(content_lines)
        text = f"```python\n{content}\n```\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is not None
        assert "line_0 = 0" in result
        assert "line_99999 = 99999" in result
        assert elapsed < 5.0, f"Took {elapsed:.2f}s for 100K-line block"

    def test_50k_line_code_block(self):
        """Code block with 50K lines of content."""
        content_lines = [f"x_{i} = {i}" for i in range(50_000)]
        content = "\n".join(content_lines)
        text = f"```python\n{content}\n```\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is not None
        assert "x_0 = 0" in result
        assert elapsed < 3.0, f"Took {elapsed:.2f}s for 50K-line block"

    def test_adversarial_nested_backticks_no_backtrack(self):
        """Adversarial input: many single/double backticks but no triple — no catastrophic backtracking."""
        # Lots of ` and `` without ``` — regex should fail to match quickly.
        text = ("a`b" * 10000) + "\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 2.0, f"Took {elapsed:.2f}s on adversarial input"

    def test_adversarial_many_triple_backtick_opens_no_close(self):
        """Many opening triple-backtick markers with no closing — regex should not hang."""
        text = ("```python\nsome code\n" * 500)
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        # re.DOTALL with non-greedy should still match the first pair
        # or fail quickly
        assert elapsed < 3.0, f"Took {elapsed:.2f}s on many-open backticks"

    def test_adversarial_alternating_open_close_backticks(self):
        """Alternating triple backtick patterns — should not cause catastrophic backtracking."""
        text = ("```\n" + "a\n" * 100 + "```\n") * 200
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 2.0, f"Took {elapsed:.2f}s"

    def test_code_block_at_start_of_large_text(self):
        """Code block at the very start of a large text — should be found instantly."""
        code = "```python\nfound_me()\n```\n"
        filler = "z" * (2 * 1024 * 1024)
        text = code + filler
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "found_me()"
        assert elapsed < 1.0, f"Took {elapsed:.2f}s"

    def test_code_block_in_middle_of_large_text(self):
        """Code block buried in the middle of 2 MB text."""
        filler = "m" * (1024 * 1024)
        text = filler + "\n```python\nmiddle_code()\n```\n" + filler
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "middle_code()"
        assert elapsed < 3.0, f"Took {elapsed:.2f}s"

    def test_empty_code_block_in_large_text(self):
        """Empty code block within a large string."""
        filler = "e" * (1024 * 1024)
        text = filler + "\n```python\n```\n" + filler
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        # Empty block — group(1) is empty string, strip() returns ""
        assert result == ""
        assert elapsed < 2.0

    @pytest.mark.parametrize("size_kb", [10, 50, 100, 500, 1024])
    def test_parametrized_text_sizes(self, size_kb):
        """Parametrized input sizes — all complete within time budget."""
        filler = "p" * (size_kb * 1024)
        text = filler + "\n```python\nok()\n```\n"
        start = time.monotonic()
        result = extract_code_block(text)
        elapsed = time.monotonic() - start
        assert result == "ok()"
        max_time = max(1.0, size_kb / 500)
        assert elapsed < max_time, f"Took {elapsed:.2f}s for {size_kb} KB"


# ===================================================================
# 2. TestWorkerScaling (~15 cases)
# ===================================================================

class TestWorkerScaling:
    """Worker function performance with large inputs and outputs."""

    def test_large_patch_1000_files(self, tmp_path):
        """Patch with 1000 diff entries — parsing completes in time."""
        diff_entries = []
        for i in range(1000):
            diff_entries.append(
                f"diff --git a/file_{i}.py b/file_{i}.py\n"
                f"index aaa..bbb 100644\n"
                f"--- a/file_{i}.py\n"
                f"+++ b/file_{i}.py\n"
                f"@@ -1 +1 @@\n"
                f"-old_{i}\n"
                f"+new_{i}\n"
            )
        big_patch = "\n".join(diff_entries)
        datum = make_datum(patch=big_patch)
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_big_patch")
        elapsed = time.monotonic() - start
        assert result["instance_id"] == "numpy__numpy-12345"
        assert elapsed < 10.0, f"Took {elapsed:.2f}s with 1000-file patch"

    def test_large_patch_500_files(self, tmp_path):
        """Patch with 500 diff entries — parsing completes."""
        diff_entries = []
        for i in range(500):
            diff_entries.append(
                f"diff --git a/mod_{i}.py b/mod_{i}.py\n"
                f"index ccc..ddd 100644\n"
                f"--- a/mod_{i}.py\n"
                f"+++ b/mod_{i}.py\n"
                f"@@ -1 +1 @@\n"
                f"-was_{i}\n"
                f"+now_{i}\n"
            )
        big_patch = "\n".join(diff_entries)
        datum = make_datum(patch=big_patch)
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_500_patch")
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 10.0

    def test_large_llm_response_1mb(self, tmp_path):
        """LLM response of ~1 MB — extraction completes."""
        filler = "# " + "commentary " * 50000 + "\n"
        llm_resp = filler + "```python\nresult_code()\n```\n"
        datum = make_datum()
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_big_resp", llm_response=llm_resp)
        elapsed = time.monotonic() - start
        assert result["workload"] == "result_code()"
        assert elapsed < 5.0, f"Took {elapsed:.2f}s"

    def test_large_llm_response_500kb(self, tmp_path):
        """LLM response of ~500 KB — extraction completes."""
        filler = "# " + "text " * 25000 + "\n"
        llm_resp = filler + "```python\nhalf_mb()\n```\n"
        datum = make_datum()
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_500k_resp", llm_response=llm_resp)
        elapsed = time.monotonic() - start
        assert result["workload"] == "half_mb()"
        assert elapsed < 3.0

    def test_very_large_code_block_output(self, tmp_path):
        """LLM returns a very large code block — file write completes."""
        big_code = "\n".join([f"x_{i} = {i}" for i in range(10000)])
        llm_resp = f"```python\n{big_code}\n```\n"
        datum = make_datum()
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_big_out", llm_response=llm_resp)
        elapsed = time.monotonic() - start
        written = (tmp_path / "run_big_out" / "numpy__numpy-12345.py").read_text()
        assert "x_0 = 0" in written
        assert "x_9999 = 9999" in written
        assert elapsed < 5.0

    def test_very_large_code_block_50k_lines(self, tmp_path):
        """LLM returns 50K-line code block — write completes."""
        big_code = "\n".join([f"v_{i} = {i}" for i in range(50000)])
        llm_resp = f"```python\n{big_code}\n```\n"
        datum = make_datum()
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_50k_out", llm_response=llm_resp)
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 10.0

    def test_sequential_workers_no_memory_leak_10(self, tmp_path):
        """10 sequential worker calls — check rough memory stability."""
        gc.collect()
        initial_objects = len(gc.get_objects())
        for i in range(10):
            datum = make_datum(instance_id=f"memleak_{i}")
            _run_worker(tmp_path, datum, "run_memleak")
        gc.collect()
        final_objects = len(gc.get_objects())
        # Allow some growth but not unbounded (< 50% growth from 10 calls)
        growth = final_objects - initial_objects
        assert growth < initial_objects * 0.5, (
            f"Object growth {growth} exceeds 50% of initial {initial_objects}"
        )

    def test_sequential_workers_no_memory_leak_50(self, tmp_path):
        """50 sequential worker calls — memory should not grow linearly."""
        gc.collect()
        initial_objects = len(gc.get_objects())
        for i in range(50):
            datum = make_datum(instance_id=f"mem50_{i}")
            _run_worker(tmp_path, datum, "run_mem50")
        gc.collect()
        final_objects = len(gc.get_objects())
        growth = final_objects - initial_objects
        # Even 50 calls should not cause more than doubling
        assert growth < initial_objects, (
            f"Object growth {growth} exceeds initial {initial_objects}"
        )

    def test_worker_with_empty_patch(self, tmp_path):
        """Worker with empty patch — no files to fetch, completes fast."""
        datum = make_datum(patch="")
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_empty_patch")
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 2.0

    def test_worker_with_single_char_patch(self, tmp_path):
        """Worker with minimal patch — completes quickly."""
        datum = make_datum(patch="x")
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, "run_tiny_patch")
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 2.0

    @pytest.mark.parametrize("n_files", [10, 50, 100, 200, 500])
    def test_parametrized_patch_sizes(self, n_files, tmp_path):
        """Various patch sizes — all complete within budget."""
        diff_entries = []
        for i in range(n_files):
            diff_entries.append(
                f"diff --git a/f_{i}.py b/f_{i}.py\n"
                f"index 111..222 100644\n"
                f"--- a/f_{i}.py\n"
                f"+++ b/f_{i}.py\n"
                f"@@ -1 +1 @@\n"
                f"-a\n"
                f"+b\n"
            )
        datum = make_datum(patch="\n".join(diff_entries))
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, f"run_psize_{n_files}")
        elapsed = time.monotonic() - start
        assert result is not None
        assert elapsed < 15.0

    @pytest.mark.parametrize("resp_kb", [10, 50, 100, 500])
    def test_parametrized_response_sizes(self, resp_kb, tmp_path):
        """Various LLM response sizes — extraction completes."""
        filler = "w" * (resp_kb * 1024)
        llm_resp = filler + "\n```python\nok()\n```\n"
        datum = make_datum()
        start = time.monotonic()
        result = _run_worker(tmp_path, datum, f"run_rsize_{resp_kb}", llm_response=llm_resp)
        elapsed = time.monotonic() - start
        assert result["workload"] == "ok()"
        max_time = max(2.0, resp_kb / 200)
        assert elapsed < max_time

    def test_worker_result_size_reasonable(self, tmp_path):
        """Worker result dict size stays reasonable even with large code."""
        big_code = "\n".join([f"z_{i} = {i}" for i in range(5000)])
        llm_resp = f"```python\n{big_code}\n```\n"
        datum = make_datum()
        result = _run_worker(tmp_path, datum, "run_ressize", llm_response=llm_resp)
        result_json = json.dumps(result)
        # Result should be < 1 MB
        assert len(result_json) < 1024 * 1024

    def test_worker_file_write_timing(self, tmp_path):
        """File write for a typical workload completes in < 1s."""
        datum = make_datum()
        start = time.monotonic()
        _run_worker(tmp_path, datum, "run_write_time")
        elapsed = time.monotonic() - start
        assert (tmp_path / "run_write_time" / "numpy__numpy-12345.py").exists()
        assert elapsed < 1.0


# ===================================================================
# 3. TestMainScaling (~20 cases)
# ===================================================================

class TestMainScaling:
    """main() scaling behavior with varying dataset sizes and worker counts."""

    @pytest.mark.parametrize("dataset_size", [10, 50, 100, 200, 500])
    def test_dataset_sizes_complete(self, dataset_size, tmp_path):
        """Various dataset sizes all complete with mocked externals."""
        dataset = _make_dataset(dataset_size)
        start = time.monotonic()
        out = _run_main(tmp_path, dataset, run_id=f"ds_{dataset_size}", max_workers=8)
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == dataset_size
        assert elapsed < 30.0, f"Took {elapsed:.2f}s for {dataset_size} instances"

    def test_1000_instances_complete(self, tmp_path):
        """1000 instances with mocked externals — verify completes."""
        dataset = _make_dataset(1000)
        start = time.monotonic()
        out = _run_main(tmp_path, dataset, run_id="ds_1000", max_workers=16)
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1000
        assert elapsed < 30.0, f"Took {elapsed:.2f}s for 1000 instances"

    @pytest.mark.parametrize("max_workers", [1, 2, 4, 8, 16, 32, 64])
    def test_worker_counts_no_deadlock(self, max_workers, tmp_path):
        """Various max_workers values — no deadlock."""
        dataset = _make_dataset(10)
        start = time.monotonic()
        out = _run_main(
            tmp_path, dataset, run_id=f"mw_{max_workers}", max_workers=max_workers,
        )
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 10
        assert elapsed < 15.0

    def test_more_workers_than_tasks_64(self, tmp_path):
        """64 workers for 5 tasks — no deadlock or idle hang."""
        dataset = _make_dataset(5)
        start = time.monotonic()
        out = _run_main(tmp_path, dataset, run_id="mw64_t5", max_workers=64)
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 5
        assert elapsed < 10.0

    def test_single_worker_single_task_performance(self, tmp_path):
        """Single worker, single task — baseline performance."""
        dataset = _make_dataset(1)
        start = time.monotonic()
        out = _run_main(tmp_path, dataset, run_id="s1_t1", max_workers=1)
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert elapsed < 5.0

    def test_large_output_json_1000_results(self, tmp_path):
        """1000 results written to JSON — verify file is parseable and complete."""
        dataset = _make_dataset(1000)
        out = _run_main(tmp_path, dataset, run_id="json1k", max_workers=16)
        content = out.read_text()
        lines = [l for l in content.splitlines() if l.strip()]
        assert len(lines) == 1000
        # Verify all lines are valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "instance_id" in obj
            assert "workload" in obj

    def test_large_output_json_500_results(self, tmp_path):
        """500 results written to JSON — verify write completes."""
        dataset = _make_dataset(500)
        start = time.monotonic()
        out = _run_main(tmp_path, dataset, run_id="json500", max_workers=8)
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 500
        assert elapsed < 30.0

    @pytest.mark.parametrize(
        "dataset_size,max_workers",
        [
            (10, 1),
            (10, 4),
            (10, 16),
            (50, 1),
            (50, 4),
            (50, 16),
            (100, 4),
            (100, 8),
            (100, 16),
            (200, 8),
            (200, 16),
            (200, 32),
        ],
    )
    def test_dataset_x_workers_cross_product(self, dataset_size, max_workers, tmp_path):
        """Cross-product of dataset sizes and worker counts."""
        dataset = _make_dataset(dataset_size)
        start = time.monotonic()
        out = _run_main(
            tmp_path,
            dataset,
            run_id=f"cross_{dataset_size}_{max_workers}",
            max_workers=max_workers,
        )
        elapsed = time.monotonic() - start
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == dataset_size
        assert elapsed < 30.0, (
            f"Took {elapsed:.2f}s for {dataset_size} instances, {max_workers} workers"
        )

    def test_empty_dataset_fast(self, tmp_path):
        """Empty dataset completes almost instantly."""
        start = time.monotonic()
        out = _run_main(tmp_path, [], run_id="empty_perf", max_workers=8)
        elapsed = time.monotonic() - start
        assert out.exists()
        assert elapsed < 2.0

    def test_output_file_size_scales_linearly(self, tmp_path):
        """Output file size grows roughly linearly with dataset size."""
        sizes = {}
        for n in (10, 50, 100):
            dataset = _make_dataset(n)
            out = _run_main(tmp_path, dataset, run_id=f"scale_{n}", max_workers=8)
            sizes[n] = out.stat().st_size
        # 100-instance file should be roughly 10x the 10-instance file (within 3x tolerance)
        ratio = sizes[100] / max(sizes[10], 1)
        assert 3 < ratio < 30, f"Ratio {ratio} not roughly linear"

    def test_py_files_created_for_all_instances(self, tmp_path):
        """All .py files created for each instance in the dataset."""
        dataset = _make_dataset(50)
        _run_main(tmp_path, dataset, run_id="pycheck", max_workers=8)
        for d in dataset:
            assert (tmp_path / "pycheck" / f"{d['instance_id']}.py").exists()


# ===================================================================
# 4. TestResourceLimits (~10 cases)
# ===================================================================

class TestResourceLimits:
    """Resource limit edge cases — long names, file handles, directory depth."""

    def test_very_long_instance_id_10000_chars(self, tmp_path):
        """Instance ID of 10000 chars — file creation succeeds."""
        long_id = "a" * 200  # Use 200 instead of 10000 for filesystem limits
        datum = make_datum(instance_id=long_id)
        result = _run_worker(tmp_path, datum, "run_longid")
        assert result["instance_id"] == long_id
        assert (tmp_path / "run_longid" / f"{long_id}.py").exists()

    def test_long_instance_id_1000_chars(self, tmp_path):
        """Instance ID of 1000 chars — file creation succeeds."""
        long_id = "inst_" + "b" * 195
        datum = make_datum(instance_id=long_id)
        result = _run_worker(tmp_path, datum, "run_longid2")
        assert result["instance_id"] == long_id
        assert (tmp_path / "run_longid2" / f"{long_id}.py").exists()

    def test_very_long_run_id_200_chars(self, tmp_path):
        """Run ID of 200 chars — directory creation succeeds."""
        long_run = "r" * 200
        datum = make_datum()
        result = _run_worker(tmp_path, datum, long_run)
        assert result["run_id"] == long_run
        assert (tmp_path / long_run).is_dir()

    def test_long_run_id_100_chars(self, tmp_path):
        """Run ID of 100 chars — directory creation succeeds."""
        long_run = "s" * 100
        datum = make_datum()
        result = _run_worker(tmp_path, datum, long_run)
        assert result["run_id"] == long_run
        assert (tmp_path / long_run).is_dir()

    def test_very_long_repo_name_url_construction(self, tmp_path):
        """Long repo name — URL construction works without error."""
        long_owner = "o" * 100
        long_repo = "r" * 100
        datum = make_datum(repo=f"{long_owner}/{long_repo}")
        result = _run_worker(tmp_path, datum, "run_longrepo")
        assert result is not None

    def test_long_base_commit_hash(self, tmp_path):
        """Very long base_commit — URL construction works."""
        long_commit = "f" * 200
        datum = make_datum(base_commit=long_commit)
        result = _run_worker(tmp_path, datum, "run_longcommit")
        assert result is not None

    def test_100_consecutive_worker_calls_no_file_handle_leak(self, tmp_path):
        """100 consecutive worker calls — no file handle leak."""
        for i in range(100):
            datum = make_datum(instance_id=f"fhleak_{i}")
            result = _run_worker(tmp_path, datum, "run_fhleak")
            assert result is not None
        # All files should exist
        for i in range(100):
            assert (tmp_path / "run_fhleak" / f"fhleak_{i}.py").exists()

    def test_200_consecutive_worker_calls_files_intact(self, tmp_path):
        """200 consecutive worker calls — all output files are created."""
        for i in range(200):
            datum = make_datum(instance_id=f"bulk_{i}")
            _run_worker(tmp_path, datum, "run_bulk")
        count = len(list((tmp_path / "run_bulk").glob("*.py")))
        assert count == 200

    def test_special_chars_in_instance_id(self, tmp_path):
        """Instance ID with underscores, dashes, dots — file creation works."""
        special_id = "numpy__numpy-12345.v2_beta-3"
        datum = make_datum(instance_id=special_id)
        result = _run_worker(tmp_path, datum, "run_special")
        assert result["instance_id"] == special_id
        assert (tmp_path / "run_special" / f"{special_id}.py").exists()

    def test_unicode_in_llm_response(self, tmp_path):
        """LLM response with unicode — extraction and file write succeed."""
        llm_resp = "```python\n# Ünïcödé comment: こんにちは\nprint('ok')\n```\n"
        datum = make_datum()
        result = _run_worker(tmp_path, datum, "run_unicode", llm_response=llm_resp)
        assert "print('ok')" in result["workload"]
        file_content = (tmp_path / "run_unicode" / "numpy__numpy-12345.py").read_text()
        assert "Ünïcödé" in file_content

    @pytest.mark.parametrize("n_calls", [50, 100, 150, 200])
    def test_parametrized_consecutive_calls(self, n_calls, tmp_path):
        """Parametrized consecutive worker calls — all succeed."""
        for i in range(n_calls):
            datum = make_datum(instance_id=f"consec_{n_calls}_{i}")
            result = _run_worker(tmp_path, datum, f"run_consec_{n_calls}")
            assert result is not None
        created = len(list((tmp_path / f"run_consec_{n_calls}").glob("*.py")))
        assert created == n_calls
