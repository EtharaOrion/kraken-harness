from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, mock_open, patch, call

import pytest

from helpers import (
    worker_function,
    main,
    extract_code_block,
    make_datum,
    make_completion_response,
    WORKLOAD_GENERATION_DIR,
)

MODULE = "swefficiency.workload.run_synthetic_generation"

# ── shared helpers ──────────────────────────────────────────────────

SAMPLE_LLM_RESPONSE_WITH_BLOCK = """Here is a workload script:

```python
import timeit
import statistics
import numpy as np

def setup():
    global arr
    np.random.seed(42)
    arr = np.random.rand(1000, 1000)

def workload():
    global arr
    _ = np.sort(arr, axis=0)

runtimes = timeit.repeat(workload, number=1, repeat=5, setup=setup)

print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
```
"""


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
    extra_patches=None,
):
    """Run main() with standard mocks; return output_path."""
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
    ctx = {
        f"{MODULE}.setup_helicone": {},
        f"{MODULE}.helicone_metadata": {"return_value": {}},
        f"{MODULE}.completion": comp_kwargs,
        f"{MODULE}.requests.get": {"side_effect": _fake_requests_get_ok},
        f"{MODULE}.load_swefficiency_dataset": {"return_value": dataset},
        f"{MODULE}.WORKLOAD_GENERATION_DIR": tmp_path,
    }
    patches = []
    for target, kw in ctx.items():
        if target == f"{MODULE}.WORKLOAD_GENERATION_DIR":
            patches.append(patch(target, kw))
        elif isinstance(kw, dict):
            patches.append(patch(target, **kw))
        else:
            patches.append(patch(target, **kw))

    if extra_patches:
        patches.extend(extra_patches)

    mgrs = [p.__enter__() for p in patches]
    try:
        main(
            dataset_name=dataset_name,
            split=split,
            instance_ids=instance_ids,
            max_workers=max_workers,
            run_id=run_id,
        )
    finally:
        for p in reversed(patches):
            p.__exit__(None, None, None)
    return tmp_path / run_id / "workload_generation.json"


# ═══════════════════════════════════════════════════════════════════
# 1. TestWorkerCompletionErrors  (~25 cases)
# ═══════════════════════════════════════════════════════════════════

# Exception types the LLM completion may raise
COMPLETION_EXCEPTIONS = [
    ConnectionError("connection refused"),
    TimeoutError("request timed out"),
    ValueError("invalid model response"),
    RuntimeError("internal LLM error"),
    OSError("network unreachable"),
    IOError("I/O interrupted"),
    Exception("generic failure"),
    ConnectionResetError("connection reset by peer"),
    BrokenPipeError("broken pipe"),
    PermissionError("auth token expired"),
    KeyError("missing key in response"),
    IndexError("choices index out of range"),
]


class TestWorkerCompletionErrors:
    """LLM completion raises various exceptions; verify retry & eventual success."""

    # ── parametrized: raise once then succeed (12 exception types) ──
    @pytest.mark.parametrize(
        "exc",
        COMPLETION_EXCEPTIONS,
        ids=[type(e).__name__ for e in COMPLETION_EXCEPTIONS],
    )
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_single_retry_then_success(self, mock_get, mock_meta, mock_sleep, exc, tmp_path):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise type(exc)(str(exc))
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_err")
        assert call_count[0] == 2
        assert result is not None
        assert result["instance_id"] == "numpy__numpy-12345"
        mock_sleep.assert_called_with(5)

    # ── parametrized: raise N times then succeed ──
    @pytest.mark.parametrize("n_failures", [2, 3, 5, 7, 10])
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_multiple_retries_then_success(self, mock_get, mock_meta, mock_sleep, n_failures, tmp_path):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] <= n_failures:
                raise ConnectionError(f"fail #{call_count[0]}")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_retry")
        assert call_count[0] == n_failures + 1
        assert result is not None
        assert mock_sleep.call_count == n_failures

    # ── sleep(5) called on each retry ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_sleep_5_on_each_retry(self, mock_get, mock_meta, mock_sleep, tmp_path):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                raise RuntimeError("fail")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_sleep")
        assert mock_sleep.call_count == 3
        for c in mock_sleep.call_args_list:
            assert c == call(5)

    # ── alternating exception types still recover ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_alternating_exception_types(self, mock_get, mock_meta, mock_sleep, tmp_path):
        call_count = [0]
        exc_cycle = [ConnectionError, TimeoutError, ValueError]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                raise exc_cycle[(call_count[0] - 1) % len(exc_cycle)]("fail")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_alt")
        assert call_count[0] == 4
        assert result is not None

    # ── error message is printed during retry ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_error_printed_during_retry(self, mock_get, mock_meta, mock_sleep, tmp_path, capsys):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("custom error message 42")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_print")
        captured = capsys.readouterr()
        assert "custom error message 42" in captured.out

    # ── result is correct after recovery ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_result_correct_after_recovery(self, mock_get, mock_meta, mock_sleep, tmp_path):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RuntimeError("fail")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(instance_id="test__recovery-1"), "run_recover")
        assert result["instance_id"] == "test__recovery-1"
        assert "import timeit" in result["workload"]

    # ── file still written after recovery ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_file_written_after_recovery(self, mock_get, mock_meta, mock_sleep, tmp_path):
        call_count = [0]

        def flaky(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                raise TimeoutError("timeout")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(instance_id="test__file-1"), "run_fwrite")
        output_file = tmp_path / "run_fwrite" / "test__file-1.py"
        assert output_file.exists()
        assert "import timeit" in output_file.read_text()


# ═══════════════════════════════════════════════════════════════════
# 2. TestWorkerGitHubFetchErrors  (~20 cases)
# ═══════════════════════════════════════════════════════════════════

GITHUB_ERROR_STATUS_CODES = [404, 500, 403, 429, 502, 503, 504, 408, 400, 401]


class TestWorkerGitHubFetchErrors:
    """requests.get returns error codes or raises exceptions during file fetch."""

    # ── parametrized: all retries fail with specific status codes ──
    @pytest.mark.parametrize("status_code", GITHUB_ERROR_STATUS_CODES)
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_all_retries_fail_status_code(self, mock_comp, mock_meta, mock_sleep, status_code, tmp_path):
        def bad_get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = status_code
            resp.text = f"Error {status_code}"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=bad_get) as mock_get,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            result = worker_function(datum, "run_gh_err")
        # max_retries=3 for each file
        assert mock_get.call_count == 3
        # completion still called despite empty file_contents
        mock_comp.assert_called_once()
        assert result is not None

    # ── requests.get raises ConnectionError ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_requests_get_raises_connection_error(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        with (
            patch(f"{MODULE}.requests.get", side_effect=ConnectionError("conn refused")),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            with pytest.raises(ConnectionError, match="conn refused"):
                worker_function(datum, "run_conn_err")

    # ── requests.get raises Timeout ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_requests_get_raises_timeout(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        import requests as req_mod

        with (
            patch(f"{MODULE}.requests.get", side_effect=req_mod.exceptions.Timeout("timed out")),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            with pytest.raises(req_mod.exceptions.Timeout):
                worker_function(datum, "run_timeout_err")

    # ── retry 2 times then succeed on 3rd ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_retry_twice_then_succeed(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        call_count = [0]

        def flaky_get(url, *a, **kw):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] <= 2:
                resp.status_code = 500
                resp.text = "Internal Server Error"
            else:
                resp.status_code = 200
                resp.text = "# file content\n"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=flaky_get),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_flaky")
        assert call_count[0] == 3
        assert result is not None

    # ── all retries exhausted with 404 → empty file_contents, LLM still called ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    def test_exhausted_retries_empty_contents_llm_called(self, mock_meta, mock_sleep, tmp_path):
        def bad_get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = 404
            resp.text = "Not Found"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=bad_get),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_exhausted")
        mock_comp.assert_called_once()
        # The user message should have empty pre_edit_code since all fetches failed
        messages = mock_comp.call_args[1]["messages"]
        user_content = messages[1]["content"]
        assert "Pre-edit source files" in user_content
        assert result is not None

    # ── multi-file patch, first file fails all retries, second succeeds ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_partial_fetch_failure_multi_file(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        two_file_patch = (
            "diff --git a/lib/foo.py b/lib/foo.py\n"
            "index 111..222 100644\n--- a/lib/foo.py\n+++ b/lib/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/lib/bar.py b/lib/bar.py\n"
            "index 333..444 100644\n--- a/lib/bar.py\n+++ b/lib/bar.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        call_count = [0]

        def mixed_get(url, *a, **kw):
            call_count[0] += 1
            resp = MagicMock()
            if "foo.py" in url:
                resp.status_code = 500
                resp.text = "error"
            else:
                resp.status_code = 200
                resp.text = "# bar content\n"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=mixed_get),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(patch=two_file_patch), "run_partial")
        # foo.py: 3 retries all fail + bar.py: 1 success = 4
        assert call_count[0] == 4
        assert result is not None

    # ── 429 rate limit with sleep between retries ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_429_rate_limit_retries(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        def rate_limited(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = 429
            resp.text = "Rate limited"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=rate_limited) as mock_get,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_429")
        assert mock_get.call_count == 3
        # sleep(1) called between retries
        assert mock_sleep.call_count >= 2

    # ── failure message printed on retry ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_failure_message_printed(self, mock_comp, mock_meta, mock_sleep, tmp_path, capsys):
        def bad_get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = 500
            resp.text = "error"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=bad_get),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_print_fail")
        captured = capsys.readouterr()
        assert "Failed to fetch" in captured.out
        assert "retrying" in captured.out

    # ── different repos with fetch failure ──
    @pytest.mark.parametrize(
        "repo",
        [
            "numpy/numpy",
            "pandas-dev/pandas",
            "scipy/scipy",
            "scikit-learn/scikit-learn",
        ],
    )
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_fetch_failure_various_repos(self, mock_comp, mock_meta, mock_sleep, repo, tmp_path):
        def bad_get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = 503
            resp.text = "unavailable"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=bad_get) as mock_get,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum(repo=repo, instance_id=f"{repo.replace('/', '__')}-err")
            result = worker_function(datum, "run_repo_err")
        assert mock_get.call_count == 3
        assert result["instance_id"] == f"{repo.replace('/', '__')}-err"


# ═══════════════════════════════════════════════════════════════════
# 3. TestWorkerFileWriteErrors  (~15 cases)
# ═══════════════════════════════════════════════════════════════════

FILE_WRITE_ERRORS = [
    (PermissionError, "Permission denied"),
    (OSError, "No space left on device"),
    (OSError, "Read-only file system"),
    (IOError, "Disk quota exceeded"),
    (FileNotFoundError, "No such file or directory"),
]


class TestWorkerFileWriteErrors:
    """Output directory creation or file write failures."""

    # ── mkdir fails with PermissionError ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_mkdir_permission_denied(self, mock_get, mock_comp, mock_meta, mock_sleep, tmp_path):
        bad_path = MagicMock(spec=Path)
        bad_path.__truediv__ = lambda self, other: bad_path
        bad_path.parent = bad_path
        bad_path.mkdir = MagicMock(side_effect=PermissionError("Permission denied"))

        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", bad_path):
            with pytest.raises(PermissionError, match="Permission denied"):
                worker_function(make_datum(), "run_mkdir_err")

    # ── parametrized: open() raises various OS errors ──
    @pytest.mark.parametrize(
        "exc_type,msg",
        FILE_WRITE_ERRORS,
        ids=[e[0].__name__ + "_" + e[1].replace(" ", "_")[:20] for e in FILE_WRITE_ERRORS],
    )
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_open_raises_error(self, mock_get, mock_comp, mock_meta, mock_sleep, exc_type, msg, tmp_path):
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch("builtins.open", side_effect=exc_type(msg)),
        ):
            with pytest.raises(exc_type, match=msg.split()[0]):
                worker_function(make_datum(), "run_open_err")

    # ── write() raises mid-stream ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_write_raises_mid_stream(self, mock_get, mock_comp, mock_meta, mock_sleep, tmp_path):
        m = mock_open()
        m.return_value.write.side_effect = OSError("Disk full")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch("builtins.open", m),
        ):
            with pytest.raises(OSError, match="Disk full"):
                worker_function(make_datum(), "run_write_err")

    # ── output path with deeply nested non-existent parent (real mkdir, real write) ──
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_deeply_nested_output_dir_created(self, mock_get, mock_comp, mock_meta, tmp_path):
        # Not an error case per se — tests that mkdir(parents=True) works
        deep_dir = tmp_path / "a" / "b" / "c"
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", deep_dir):
            result = worker_function(make_datum(instance_id="test__deep-1"), "run_deep")
        output_file = deep_dir / "run_deep" / "test__deep-1.py"
        assert output_file.exists()

    # ── OSError on mkdir with errno ──
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_mkdir_oserror(self, mock_get, mock_comp, mock_meta, mock_sleep, tmp_path):
        bad_path = MagicMock(spec=Path)
        bad_path.__truediv__ = lambda self, other: bad_path
        bad_path.parent = bad_path
        bad_path.mkdir = MagicMock(side_effect=OSError(28, "No space left on device"))

        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", bad_path):
            with pytest.raises(OSError):
                worker_function(make_datum(), "run_mkdir_os")

    # ── parametrized: multiple instance_ids with write error ──
    @pytest.mark.parametrize(
        "instance_id",
        [
            "numpy__numpy-write-err-0",
            "numpy__numpy-write-err-1",
            "numpy__numpy-write-err-2",
            "pandas-dev__pandas-write-err-0",
        ],
    )
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_write_error_various_instances(self, mock_get, mock_comp, mock_meta, mock_sleep, instance_id, tmp_path):
        m = mock_open()
        m.return_value.write.side_effect = OSError("I/O error")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch("builtins.open", m),
        ):
            with pytest.raises(OSError, match="I/O error"):
                worker_function(make_datum(instance_id=instance_id), "run_wv")


# ═══════════════════════════════════════════════════════════════════
# 4. TestMainDatasetErrors  (~15 cases)
# ═══════════════════════════════════════════════════════════════════

DATASET_EXCEPTIONS = [
    FileNotFoundError("dataset not found"),
    ValueError("invalid dataset format"),
    ConnectionError("cannot reach HuggingFace"),
    RuntimeError("dataset corrupted"),
    PermissionError("access denied"),
    OSError("disk error reading dataset"),
    KeyError("missing split"),
    ImportError("datasets package not installed"),
    TimeoutError("download timed out"),
    Exception("unknown error"),
]


class TestMainDatasetErrors:
    """load_swefficiency_dataset raises or returns bad data."""

    # ── parametrized: load raises various exceptions ──
    @pytest.mark.parametrize(
        "exc",
        DATASET_EXCEPTIONS,
        ids=[type(e).__name__ + "_" + str(e).split()[0][:15] for e in DATASET_EXCEPTIONS],
    )
    def test_load_dataset_raises(self, exc, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", side_effect=type(exc)(str(exc))),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            with pytest.raises(type(exc)):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_ds_err",
                )

    # ── dataset with missing 'patch' field ──
    def test_malformed_instance_missing_patch(self, tmp_path):
        bad_dataset = [{"instance_id": "test-1", "repo": "numpy/numpy", "base_commit": "abc123"}]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=bad_dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        ):
            with pytest.raises(KeyError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_no_patch",
                )

    # ── dataset with missing 'repo' field ──
    def test_malformed_instance_missing_repo(self, tmp_path):
        bad_dataset = [{"instance_id": "test-1", "patch": "diff --git a/f.py b/f.py\n", "base_commit": "abc"}]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=bad_dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        ):
            with pytest.raises(KeyError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_no_repo",
                )

    # ── dataset with missing 'base_commit' field ──
    def test_malformed_instance_missing_base_commit(self, tmp_path):
        bad_dataset = [{"instance_id": "test-1", "repo": "numpy/numpy", "patch": "diff --git a/f.py b/f.py\n"}]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=bad_dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        ):
            with pytest.raises(KeyError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_no_commit",
                )

    # ── dataset with missing 'instance_id' field ──
    def test_malformed_instance_missing_instance_id(self, tmp_path):
        bad_dataset = [{"repo": "numpy/numpy", "patch": "diff --git a/f.py b/f.py\n", "base_commit": "abc"}]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=bad_dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        ):
            with pytest.raises(KeyError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_no_iid",
                )

    # ── repo field with wrong format (no slash) ──
    def test_malformed_repo_no_slash(self, tmp_path):
        bad_dataset = [make_datum(repo="numpynumpy")]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=bad_dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
        ):
            with pytest.raises(ValueError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_bad_repo",
                )


# ═══════════════════════════════════════════════════════════════════
# 5. TestMainThreadPoolErrors  (~15 cases)
# ═══════════════════════════════════════════════════════════════════

WORKER_EXCEPTIONS = [
    ConnectionError("worker connection error"),
    RuntimeError("worker runtime error"),
    ValueError("worker value error"),
    OSError("worker OS error"),
    TimeoutError("worker timeout"),
    KeyError("worker key error"),
    IndexError("worker index error"),
    TypeError("worker type error"),
    MemoryError("worker OOM"),
    OverflowError("worker overflow"),
]


class TestMainThreadPoolErrors:
    """Worker raises unhandled exception — verify future.result() propagates."""

    @pytest.mark.parametrize(
        "exc",
        WORKER_EXCEPTIONS,
        ids=[type(e).__name__ for e in WORKER_EXCEPTIONS],
    )
    def test_worker_unhandled_exception_propagates(self, exc, tmp_path):
        dataset = _make_dataset(1)
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=type(exc)(str(exc))),
        ):
            with pytest.raises(type(exc)):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_tpe_prop",
                )


    @pytest.mark.parametrize(
        "exc",
        WORKER_EXCEPTIONS[:5],
        ids=[type(e).__name__ + "_direct" for e in WORKER_EXCEPTIONS[:5]],
    )
    def test_worker_direct_raise_propagates(self, exc, tmp_path):
        dataset = _make_dataset(1)
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=type(exc)(str(exc))),
        ):
            with pytest.raises(type(exc)):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_tpe_err",
                )

    # ── multiple workers, one fails ──
    def test_one_of_multiple_workers_fails(self, tmp_path):
        dataset = _make_dataset(3)
        call_idx = [0]

        def flaky_worker(datum, run_id):
            call_idx[0] += 1
            if call_idx[0] == 2:
                raise RuntimeError("worker 2 failed")
            return {
                "instance_id": datum["instance_id"],
                "run_id": run_id,
                "workload": "pass",
            }

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=flaky_worker),
        ):
            with pytest.raises(RuntimeError, match="worker 2 failed"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_partial_fail",
                )

    # ── ThreadPoolExecutor creation fails ──
    def test_thread_pool_executor_creation_fails(self, tmp_path):
        dataset = _make_dataset(2)
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.ThreadPoolExecutor", side_effect=RuntimeError("cannot create thread pool")),
        ):
            with pytest.raises(RuntimeError, match="cannot create thread pool"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_tpe_create",
                )

    # ── all workers fail ──
    def test_all_workers_fail(self, tmp_path):
        dataset = _make_dataset(3)

        def always_fail(datum, run_id):
            raise ValueError(f"fail for {datum['instance_id']}")

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=always_fail),
        ):
            with pytest.raises(ValueError, match="fail for"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=2,
                    run_id="run_all_fail",
                )

    # ── parametrized: various max_workers with failure ──
    @pytest.mark.parametrize("max_workers", [1, 2, 4, 8, 16])
    def test_failure_with_various_workers(self, max_workers, tmp_path):
        dataset = _make_dataset(2)

        def fail_worker(datum, run_id):
            raise OSError("worker error")

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=fail_worker),
        ):
            with pytest.raises(OSError, match="worker error"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=max_workers,
                    run_id=f"run_w{max_workers}",
                )


# ═══════════════════════════════════════════════════════════════════
# 6. TestMainOutputErrors  (~10 cases)
# ═══════════════════════════════════════════════════════════════════


class TestMainOutputErrors:
    """Output path is read-only, JSON write fails, WORKLOAD_GENERATION_DIR issues."""

    # ── WORKLOAD_GENERATION_DIR.mkdir raises PermissionError ──
    def test_workload_dir_mkdir_permission_denied(self, tmp_path):
        bad_dir = MagicMock(spec=Path)
        bad_dir.mkdir = MagicMock(side_effect=PermissionError("Cannot create directory"))
        bad_dir.__truediv__ = lambda self, other: bad_dir

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", bad_dir),
        ):
            with pytest.raises(PermissionError, match="Cannot create directory"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_dir_err",
                )

    # ── output JSON write fails with OSError ──
    def test_output_json_write_fails(self, tmp_path):
        dataset = _make_dataset(2)

        m = mock_open()
        m.return_value.write.side_effect = OSError("Disk full during JSON write")

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            # Override just the final open call for the JSON output
            # The worker's open calls succeed (using real filesystem)
            # but the main's open for workload_generation.json fails
            original_open = open

            def selective_open(path, *args, **kwargs):
                if str(path).endswith("workload_generation.json"):
                    raise OSError("Disk full during JSON write")
                return original_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=selective_open):
                with pytest.raises(OSError, match="Disk full"):
                    main(
                        dataset_name="test",
                        split="test",
                        instance_ids=[],
                        max_workers=1,
                        run_id="run_json_err",
                    )

    # ── output dir mkdir raises OSError ──
    def test_output_dir_mkdir_oserror(self, tmp_path):
        # Make the base dir exist but make the run subdir creation fail
        counter = [0]
        original_mkdir = Path.mkdir

        def failing_mkdir(self, *args, **kwargs):
            counter[0] += 1
            # Fail on first mkdir call (WORKLOAD_GENERATION_DIR.mkdir)
            if counter[0] == 1:
                raise OSError(28, "No space left on device")
            return original_mkdir(self, *args, **kwargs)

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path / "new_base"),
            patch.object(Path, "mkdir", failing_mkdir),
        ):
            with pytest.raises(OSError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_odir_err",
                )

    # ── parametrized: various OSError errno values on dir creation ──
    @pytest.mark.parametrize(
        "errno_val,msg",
        [
            (13, "Permission denied"),
            (28, "No space left on device"),
            (30, "Read-only file system"),
            (122, "Disk quota exceeded"),
        ],
    )
    def test_output_dir_various_os_errors(self, errno_val, msg, tmp_path):
        bad_dir = MagicMock(spec=Path)
        bad_dir.mkdir = MagicMock(side_effect=OSError(errno_val, msg))
        bad_dir.__truediv__ = lambda self, other: bad_dir

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", bad_dir),
        ):
            with pytest.raises(OSError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_oe",
                )

    # ── json.dumps raises for non-serializable result ──
    def test_json_dumps_raises_for_bad_result(self, tmp_path):
        dataset = _make_dataset(1)

        def bad_worker(datum, run_id):
            return {
                "instance_id": datum["instance_id"],
                "run_id": run_id,
                "workload": object(),  # not JSON serializable
            }

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=bad_worker),
        ):
            with pytest.raises(TypeError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_json_serial",
                )

    # ── setup_helicone raises ──
    def test_setup_helicone_raises(self, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone", side_effect=RuntimeError("helicone setup failed")),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            with pytest.raises(RuntimeError, match="helicone setup failed"):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_heli_err",
                )

    # ── WORKLOAD_GENERATION_DIR is a file, not a directory ──
    def test_workload_dir_is_file(self, tmp_path):
        fake_file = tmp_path / "not_a_dir"
        fake_file.write_text("I am a file")

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", fake_file),
        ):
            with pytest.raises((NotADirectoryError, OSError, FileExistsError)):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_file_dir",
                )

    # ── output_dir exists as a file blocking directory creation ──
    def test_output_run_dir_is_file(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        blocking_file = tmp_path / "blocked_run"
        blocking_file.write_text("I block directory creation")

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            with pytest.raises((NotADirectoryError, OSError, FileExistsError)):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="blocked_run",
                )
