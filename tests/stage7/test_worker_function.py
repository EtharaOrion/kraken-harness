from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from helpers import (
    SAMPLE_CODE_BLOCK,
    SAMPLE_LLM_RESPONSE_NO_BLOCK,
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
    SAMPLE_PATCH,
    SAMPLE_PATCH_TWO_FILES,
    extract_code_block,
    make_completion_response,
    make_datum,
    worker_function,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


def _fake_requests_get_ok(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = f"# content of {url}\npass\n"
    return resp


def _fake_requests_get_404(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 404
    resp.text = "Not Found"
    return resp


# ---------------------------------------------------------------------------
# Existing test classes (preserved verbatim)
# ---------------------------------------------------------------------------


class TestWorkerBasicFlow:
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_returns_dict_with_required_keys(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        assert "instance_id" in result
        assert "run_id" in result
        assert "workload" in result

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_instance_id_preserved(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id="numpy__numpy-99999")
            result = worker_function(datum, "run_001")
        assert result["instance_id"] == "numpy__numpy-99999"

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_preserved(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, "my_run_42")
        assert result["run_id"] == "my_run_42"

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_workload_contains_extracted_code(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        assert "import timeit" in result["workload"]
        assert "def setup():" in result["workload"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_NO_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_no_code_block_returns_raw_response(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        assert result["workload"] == SAMPLE_LLM_RESPONSE_NO_BLOCK


class TestWorkerFileOutput:
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_file_created(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id="test__inst_1")
            worker_function(datum, "run_001")
        output_file = tmp_path / "run_001" / "test__inst_1.py"
        assert output_file.exists()

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_file_contains_code(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id="test__inst_1")
            worker_function(datum, "run_001")
        content = (tmp_path / "run_001" / "test__inst_1.py").read_text()
        assert "import timeit" in content

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_NO_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_file_empty_when_no_code_block(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id="test__inst_1")
            worker_function(datum, "run_001")
        content = (tmp_path / "run_001" / "test__inst_1.py").read_text()
        assert content == ""

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_output_dir_created_automatically(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id="test__inst_1")
            worker_function(datum, "new_run_id")
        assert (tmp_path / "new_run_id").is_dir()


class TestWorkerGitHubFetch:
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_fetches_files_from_patch(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(patch=SAMPLE_PATCH)
            worker_function(datum, "run_001")
        assert mock_get.call_count == 1
        url = mock_get.call_args[0][0]
        assert "numpy/core/fromnumeric.py" in url
        assert "abc123def456" in url

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_fetches_multiple_files(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(patch=SAMPLE_PATCH_TWO_FILES)
            worker_function(datum, "run_001")
        assert mock_get.call_count == 2
        urls = [c[0][0] for c in mock_get.call_args_list]
        assert any("lib/foo.py" in u for u in urls)
        assert any("lib/bar.py" in u for u in urls)

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_retries_on_fetch_failure(self, mock_comp, mock_meta, mock_sleep, tmp_path):
        call_count = [0]
        def flaky_get(url, *a, **kw):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] <= 2:
                resp.status_code = 500
            else:
                resp.status_code = 200
                resp.text = "# content\n"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=flaky_get),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        assert call_count[0] == 3
        assert result is not None

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_404)
    def test_max_retries_exhausted(self, mock_get, mock_comp, mock_meta, mock_sleep, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        assert mock_get.call_count == 3
        assert result is not None

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_url_format(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(repo="scipy/scipy", base_commit="deadbeef1234")
            worker_function(datum, "run_001")
        url = mock_get.call_args[0][0]
        assert url.startswith("https://raw.githubusercontent.com/scipy/scipy/deadbeef1234/")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_patch_no_fetch(self, mock_get, mock_comp, mock_meta, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(patch="just some text without diff markers")
            worker_function(datum, "run_001")
        mock_get.assert_not_called()


class TestWorkerLLMCall:
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_completion_called_with_system_msg(self, mock_get, mock_meta, tmp_path):
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            worker_function(datum, "run_001")
        messages = mock_comp.call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert "performance testing expert" in messages[0]["content"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_completion_called_with_context(self, mock_get, mock_meta, tmp_path):
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum(repo="numpy/numpy")
            worker_function(datum, "run_001")
        messages = mock_comp.call_args[1]["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 2
        assert "numpy" in user_msgs[0]["content"]
        assert "Commit Diff" in user_msgs[0]["content"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_temperature_zero(self, mock_get, mock_meta, tmp_path):
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["temperature"] == 0.0

    @patch(f"{MODULE}.helicone_metadata", return_value={"key": "val"})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_metadata_passed_to_completion(self, mock_get, mock_meta, tmp_path):
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["metadata"] == {"key": "val"}

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_model_from_env(self, mock_get, mock_meta, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_MODEL", "bedrock/custom-model-v2")
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["model"] == "bedrock/custom-model-v2"

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_default_model(self, mock_get, mock_meta, tmp_path, monkeypatch):
        monkeypatch.delenv("WORKLOAD_MODEL", raising=False)
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert "anthropic" in mock_comp.call_args[1]["model"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_api_base_from_env(self, mock_get, mock_meta, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_BEDROCK_RUNTIME_ENDPOINT", "https://custom.endpoint")
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["api_base"] == "https://custom.endpoint"

    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_completion_retry_on_exception(self, mock_get, mock_meta, mock_sleep, tmp_path):
        call_count = [0]
        def flaky_completion(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("LLM error")
            return make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)

        with (
            patch(f"{MODULE}.completion", side_effect=flaky_completion),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            result = worker_function(make_datum(), "run_001")
        assert call_count[0] == 2
        assert result is not None


# ---------------------------------------------------------------------------
# Data variants for parametrized tests
# ---------------------------------------------------------------------------

REPO_VARIANTS = [
    ("numpy/numpy", "numpy"),
    ("pandas-dev/pandas", "pandas"),
    ("scipy/scipy", "scipy"),
    ("scikit-learn/scikit-learn", "scikit-learn"),
    ("matplotlib/matplotlib", "matplotlib"),
    ("pydata/xarray", "xarray"),
    ("sympy/sympy", "sympy"),
    ("dask/dask", "dask"),
    ("astropy/astropy", "astropy"),
]


def _make_simple_diff(filepath: str) -> str:
    """Helper to build a minimal valid diff for a single file."""
    return (
        f"diff --git a/{filepath} b/{filepath}\n"
        f"index 111..222 100644\n"
        f"--- a/{filepath}\n"
        f"+++ b/{filepath}\n"
        f"@@ -1 +1 @@\n"
        f"-old\n"
        f"+new\n"
    )


def _make_multi_diff(filepaths: list) -> str:
    """Helper to concatenate multiple single-file diffs."""
    return "".join(_make_simple_diff(fp) for fp in filepaths)


PATCH_VARIANTS = [
    # --- original 5 ---
    (
        "single file",
        "diff --git a/src/core.py b/src/core.py\nindex 111..222 100644\n--- a/src/core.py\n+++ b/src/core.py\n@@ -1 +1 @@\n-old\n+new\n",
        1,
    ),
    (
        "two files",
        SAMPLE_PATCH_TWO_FILES,
        2,
    ),
    (
        "three files",
        (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-x\n+y\n"
        ),
        3,
    ),
    (
        "no diff header",
        "some random text",
        0,
    ),
    (
        "nested path",
        "diff --git a/deep/nested/path/file.py b/deep/nested/path/file.py\nindex 111..222 100644\n--- a/deep/nested/path/file.py\n+++ b/deep/nested/path/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        1,
    ),
    # --- 45 new variants (indices 5-49) ---
    ("four_files", _make_multi_diff(["w.py", "x.py", "y.py", "z.py"]), 4),
    ("five_files", _make_multi_diff(["a1.py", "a2.py", "a3.py", "a4.py", "a5.py"]), 5),
    ("six_files", _make_multi_diff([f"f{i}.py" for i in range(6)]), 6),
    ("seven_files", _make_multi_diff([f"mod{i}.py" for i in range(7)]), 7),
    ("eight_files", _make_multi_diff([f"pkg/m{i}.py" for i in range(8)]), 8),
    ("nine_files", _make_multi_diff([f"src/m{i}.py" for i in range(9)]), 9),
    ("ten_files", _make_multi_diff([f"lib/m{i}.py" for i in range(10)]), 10),
    ("deeply_nested_1", _make_simple_diff("a/b/c/d/e/f/g/h.py"), 1),
    ("deeply_nested_2", _make_simple_diff("src/core/internal/impl/detail/utils.py"), 1),
    ("deeply_nested_3", _make_simple_diff("packages/sub/src/lib/helpers/convert.py"), 1),
    ("init_py", _make_simple_diff("mypackage/__init__.py"), 1),
    ("conftest_py", _make_simple_diff("tests/conftest.py"), 1),
    ("setup_py", _make_simple_diff("setup.py"), 1),
    ("setup_cfg", _make_simple_diff("setup.cfg"), 1),
    ("pyproject_toml", _make_simple_diff("pyproject.toml"), 1),
    ("c_extension", _make_simple_diff("src/module.c"), 1),
    ("header_file", _make_simple_diff("include/module.h"), 1),
    ("pyx_file", _make_simple_diff("src/_fast.pyx"), 1),
    ("rst_file", _make_simple_diff("docs/guide.rst"), 1),
    ("md_file", _make_simple_diff("docs/README.md"), 1),
    ("txt_file", _make_simple_diff("CHANGES.txt"), 1),
    ("yaml_file", _make_simple_diff(".github/workflows/ci.yaml"), 1),
    ("json_file", _make_simple_diff("package.json"), 1),
    ("toml_file", _make_simple_diff("config.toml"), 1),
    ("dockerfile", _make_simple_diff("Dockerfile"), 1),
    ("makefile", _make_simple_diff("Makefile"), 1),
    ("dot_gitignore", _make_simple_diff(".gitignore"), 1),
    ("test_file", _make_simple_diff("tests/test_core.py"), 1),
    ("bench_file", _make_simple_diff("benchmarks/bench_sort.py"), 1),
    ("cython_pxd", _make_simple_diff("src/_types.pxd"), 1),
    ("empty_text_no_diff", "no diff content here", 0),
    ("whitespace_only", "   \n\n  \t  \n", 0),
    ("partial_diff_header", "diff --git but malformed", 0),
    ("mixed_valid_invalid", "noise\n" + _make_simple_diff("real.py") + "more noise", 1),
    ("path_with_dots", _make_simple_diff("src/v2.0/core.utils.py"), 1),
    ("path_with_hyphens", _make_simple_diff("my-package/my-module.py"), 1),
    ("path_with_underscores", _make_simple_diff("my_package/my_module.py"), 1),
    ("very_long_path", _make_simple_diff("/".join(["d"] * 20) + "/file.py"), 1),
    ("single_char_filename", _make_simple_diff("x"), 1),
    ("numeric_filename", _make_simple_diff("123.py"), 1),
    ("init_nested", _make_simple_diff("a/b/c/__init__.py"), 1),
    ("two_inits", _make_multi_diff(["pkg/__init__.py", "pkg/sub/__init__.py"]), 2),
    ("mix_py_and_c", _make_multi_diff(["src/mod.py", "src/mod.c", "src/mod.h"]), 3),
    ("large_diff_100_lines", (
        "diff --git a/big.py b/big.py\nindex 111..222 100644\n--- a/big.py\n+++ b/big.py\n@@ -1,100 +1,100 @@\n"
        + "".join(f"-line {i}\n+line {i} changed\n" for i in range(100))
    ), 1),
    ("renamed_file_style", (
        "diff --git a/old_name.py b/new_name.py\n"
        "similarity index 95%\n"
        "rename from old_name.py\n"
        "rename to new_name.py\n"
        "index 111..222 100644\n"
        "--- a/old_name.py\n"
        "+++ b/new_name.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    ), 1),
]

# Confirm we have exactly 50
assert len(PATCH_VARIANTS) == 50, f"Expected 50 PATCH_VARIANTS, got {len(PATCH_VARIANTS)}"


COMMIT_HASHES = [
    # --- original 5 ---
    "a" * 40,
    "0" * 40,
    "deadbeef",
    "abc123",
    "1234567890abcdef1234567890abcdef12345678",
    # --- 45 new variants ---
    "b" * 40,
    "c" * 40,
    "d" * 40,
    "e" * 40,
    "f" * 40,
    "0123456789abcdef" * 2 + "01234567",
    "fedcba9876543210" * 2 + "fedcba98",
    "abcdef",
    "012345",
    "a1b2c3",
    "a1b2c3d4e5f6",
    "0a1b2c3d",
    "f0e1d2c3",
    "aabbccdd",
    "11223344",
    "55667788",
    "99aabbcc",
    "ddeeff00",
    "a0b0c0d0",
    "1a2b3c4d",
    "5e6f7a8b",
    "9c0d1e2f",
    "abcd1234",
    "5678ef90",
    "face0ff0",
    "babe1234",
    "cafe5678",
    "deed9abc",
    "beef0def",
    "1111aaaa",
    "2222bbbb",
    "3333cccc",
    "4444dddd",
    "5555eeee",
    "6666ffff",
    "7777" * 10,
    "8888" * 10,
    "9999" * 10,
    "aaaa" * 10,
    "bbbb" * 10,
    "cccc" * 10,
    "dddd" * 10,
    "eeee" * 10,
    "ffff" * 10,
    "0000" * 10,
]

assert len(COMMIT_HASHES) == 50, f"Expected 50 COMMIT_HASHES, got {len(COMMIT_HASHES)}"


RUN_IDS = [
    # --- original 5 ---
    "run_001",
    "experiment_2025",
    "test-run",
    "a" * 100,
    "run/with/slashes",
    # --- 115 new variants (total 120) ---
    "run_002",
    "run_003",
    "run_004",
    "run_005",
    "run_006",
    "run_007",
    "run_008",
    "run_009",
    "run_010",
    "run_011",
    "run_012",
    "run_013",
    "run_014",
    "run_015",
    "run_016",
    "run_017",
    "run_018",
    "run_019",
    "run_020",
    "run_021",
    "run_022",
    "run_023",
    "run_024",
    "run_025",
    "run_026",
    "run_027",
    "run_028",
    "run_029",
    "run_030",
    "run_031",
    "experiment_alpha",
    "experiment_beta",
    "experiment_gamma",
    "experiment_delta",
    "experiment_epsilon",
    "2025-01-15T10-30-00",
    "2025-02-20T14-45-30",
    "2025-03-01T00-00-00",
    "2025-04-10T23-59-59",
    "2025-05-05T12-00-00",
    "2025-06-15T08-30-00",
    "2025-07-04T16-20-10",
    "2025-08-22T09-15-45",
    "2025-09-30T11-11-11",
    "2025-10-31T22-22-22",
    "bench-v1.0",
    "bench-v1.1",
    "bench-v2.0",
    "bench-v2.1-rc1",
    "bench-v3.0-alpha",
    "perf_test_001",
    "perf_test_002",
    "perf_test_003",
    "perf_test_004",
    "perf_test_005",
    "nightly-build-100",
    "nightly-build-101",
    "nightly-build-102",
    "nightly-build-103",
    "nightly-build-104",
    "ci-pipeline-abc",
    "ci-pipeline-def",
    "ci-pipeline-ghi",
    "ci-pipeline-jkl",
    "ci-pipeline-mno",
    "user.alice.run1",
    "user.bob.run2",
    "user.charlie.run3",
    "user.dave.run4",
    "user.eve.run5",
    "x",
    "X",
    "0",
    "1",
    "42",
    "999",
    "run-with-many-hyphens-in-name",
    "run_with_many_underscores_in_name",
    "run.with.many.dots.in.name",
    "MixedCaseRunId",
    "ALLCAPS",
    "alllower",
    "CamelCaseRun",
    "snake_case_run",
    "kebab-case-run",
    "b" * 100,
    "c" * 50,
    "z" * 200,
    "run_with_numbers_123456789",
    "123_numeric_start",
    "___triple_underscore",
    "---triple-hyphen",
    "...triple-dot",
    "run__double__underscore",
    "run--double--hyphen",
    "a-b_c.d",
    "test/nested/deep/path/run",
    "test/a",
    "single",
    "ab",
    "run_100",
    "run_200",
    "run_300",
    "run_400",
    "run_500",
    "run_600",
    "run_700",
    "run_800",
    "run_900",
    "run_999",
    "final-run",
    "the-last-run",
    "one-more-run",
    "yet-another-run",
    "penultimate-run",
]

assert len(RUN_IDS) == 120, f"Expected 120 RUN_IDS, got {len(RUN_IDS)}"


# Instance ID variants for file output tests
INSTANCE_ID_VARIANTS = [
    "numpy__numpy-12345",
    "pandas-dev__pandas-99999",
    "scipy__scipy-1",
    "scikit-learn__scikit-learn-55555",
    "matplotlib__matplotlib-0",
    "pydata__xarray-42",
    "sympy__sympy-100000",
    "dask__dask-7777",
    "astropy__astropy-88888",
    "test__simple",
    "a__b-1",
    "very-long-org__very-long-repo-name-with-many-chars-99999",
    "x__y-0",
    "UPPER__CASE-123",
    "mixed__Case-456",
    "num123__repo456-789",
    "has.dots__in.name-1",
    "has-hyphens__in-name-2",
    "has_underscores__in_name-3",
    "org__repo-1",
    "org__repo-2",
    "org__repo-3",
    "org__repo-10",
    "org__repo-100",
    "org__repo-1000",
    "org__repo-10000",
    "org__repo-100000",
    "org__repo-999999",
    "a__a-0",
    "ab__cd-1",
    "abc__def-12",
    "abcd__efgh-123",
    "abcde__fghij-1234",
    "org__repo-00001",
    "org__repo-00010",
    "org__repo-00100",
    "test__double__underscore-1",
    "test__triple___underscore-2",
    "CamelCase__Repo-42",
    "lowercase__repo-42",
    "with123numbers__repo456-789",
    "z" * 50 + "__" + "z" * 50 + "-1",
    "short__s-0",
    "numpy__numpy-1",
    "numpy__numpy-2",
    "numpy__numpy-3",
    "numpy__numpy-4",
    "numpy__numpy-5",
    "numpy__numpy-6",
    "numpy__numpy-7",
]

assert len(INSTANCE_ID_VARIANTS) == 50, f"Expected 50 INSTANCE_ID_VARIANTS, got {len(INSTANCE_ID_VARIANTS)}"


# Model name variants for LLM call tests
MODEL_VARIANTS = [
    "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
    "bedrock/custom-model-v2",
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4o",
    "gpt-3.5-turbo",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
    "claude-3-5-sonnet-20241022",
    "anthropic/claude-3-opus",
    "anthropic/claude-3-sonnet",
    "bedrock/anthropic.claude-v2",
    "bedrock/meta.llama3-70b-instruct-v1",
    "vertex_ai/gemini-1.5-pro",
    "vertex_ai/gemini-1.5-flash",
    "together_ai/meta-llama/Llama-3-70b",
    "openai/gpt-4o-mini",
    "azure/gpt-4-deployment",
    "ollama/llama3",
]

assert len(MODEL_VARIANTS) == 20, f"Expected 20 MODEL_VARIANTS, got {len(MODEL_VARIANTS)}"


API_BASE_VARIANTS = [
    "https://custom.endpoint",
    "https://api.openai.com/v1",
    "https://bedrock-runtime.us-east-1.amazonaws.com",
    "https://bedrock-runtime.us-west-2.amazonaws.com",
    "https://bedrock-runtime.eu-west-1.amazonaws.com",
    "https://bedrock-runtime.ap-southeast-1.amazonaws.com",
    "https://my-proxy.example.com/api",
    "https://localhost:8080",
    "https://10.0.0.1:443/v1",
    "https://api.anthropic.com",
    "https://generativelanguage.googleapis.com",
    "http://localhost:11434",
    "https://api.together.xyz/v1",
    "https://inference.example.org",
    "https://gateway.ai.cloudflare.com/v1/abc/def/openai",
    "https://my-company-llm.internal.net/api/v2",
    "https://us-central1-aiplatform.googleapis.com",
    "https://eastus.api.cognitive.microsoft.com",
    "https://models.inference.ai.azure.com",
    "https://custom-endpoint.mycompany.io/llm",
]

assert len(API_BASE_VARIANTS) == 20, f"Expected 20 API_BASE_VARIANTS, got {len(API_BASE_VARIANTS)}"


# Status code variants for GitHub fetch retry tests
RETRY_STATUS_CODES = [
    403, 404, 429, 500, 502, 503, 504, 408, 410, 418,
    400, 401, 405, 406, 407, 409, 411, 413, 414, 415,
]

assert len(RETRY_STATUS_CODES) == 20, f"Expected 20 RETRY_STATUS_CODES, got {len(RETRY_STATUS_CODES)}"


# Metadata variant dicts
METADATA_VARIANTS = [
    {},
    {"key": "val"},
    {"model": "test", "run": "1"},
    {"nested": {"a": 1}},
    {"list_val": [1, 2, 3]},
    {"empty_str": ""},
    {"num": 42},
    {"bool_true": True},
    {"bool_false": False},
    {"none_val": None},
]

assert len(METADATA_VARIANTS) == 10, f"Expected 10 METADATA_VARIANTS, got {len(METADATA_VARIANTS)}"


# ---------------------------------------------------------------------------
# Existing parametrized test classes (preserved, now using expanded data)
# ---------------------------------------------------------------------------


class TestWorkerAllRepos:
    @pytest.mark.parametrize("repo,repo_name", REPO_VARIANTS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_all_nine_repos(self, mock_get, mock_comp, mock_meta, repo, repo_name, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(repo=repo, instance_id=f"{repo.replace('/', '__')}-123")
            result = worker_function(datum, "run_001")
        assert result["instance_id"] == f"{repo.replace('/', '__')}-123"
        messages = mock_comp.call_args[1]["messages"]
        user_content = messages[1]["content"]
        assert repo_name in user_content


class TestWorkerPatchParsing:
    @pytest.mark.parametrize(
        "name,diff_patch,expected_fetch_count",
        PATCH_VARIANTS,
        ids=[p[0] for p in PATCH_VARIANTS],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_patch_file_count(self, mock_get, mock_comp, mock_meta, name, diff_patch, expected_fetch_count, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(patch=diff_patch)
            worker_function(datum, "run_001")
        assert mock_get.call_count == expected_fetch_count


class TestWorkerCommitVariants:
    @pytest.mark.parametrize("commit", COMMIT_HASHES)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_various_commit_hashes(self, mock_get, mock_comp, mock_meta, commit, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(base_commit=commit)
            result = worker_function(datum, "run_001")
        assert result is not None
        url = mock_get.call_args[0][0]
        assert commit in url


class TestWorkerRunIdVariants:
    @pytest.mark.parametrize("run_id", RUN_IDS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_various_run_ids(self, mock_get, mock_comp, mock_meta, run_id, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum()
            result = worker_function(datum, run_id)
        assert result["run_id"] == run_id


# ---------------------------------------------------------------------------
# NEW: Cross-product test classes
# ---------------------------------------------------------------------------


class TestWorkerRepoXPatch:
    """Cross-product: 9 repos x 50 patches = 450 tests."""

    @pytest.mark.parametrize("repo,repo_name", REPO_VARIANTS)
    @pytest.mark.parametrize(
        "pname,diff_patch,expected_fetch_count",
        PATCH_VARIANTS,
        ids=[p[0] for p in PATCH_VARIANTS],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_patch_cross(self, mock_get, mock_comp, mock_meta, repo, repo_name, pname, diff_patch, expected_fetch_count, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(repo=repo, patch=diff_patch, instance_id=f"{repo.replace('/', '__')}-xpatch")
            result = worker_function(datum, "run_001")
        assert result is not None
        assert result["instance_id"] == f"{repo.replace('/', '__')}-xpatch"
        assert mock_get.call_count == expected_fetch_count


class TestWorkerRepoXCommit:
    """Cross-product: 9 repos x 50 commits = 450 tests."""

    @pytest.mark.parametrize("repo,repo_name", REPO_VARIANTS)
    @pytest.mark.parametrize("commit", COMMIT_HASHES)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_commit_cross(self, mock_get, mock_comp, mock_meta, repo, repo_name, commit, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(repo=repo, base_commit=commit, instance_id=f"{repo.replace('/', '__')}-xcommit")
            result = worker_function(datum, "run_001")
        assert result is not None
        url = mock_get.call_args[0][0]
        assert commit in url
        owner, rname = repo.split("/")
        assert owner in url


class TestWorkerRepoXRunId:
    """Cross-product: 9 repos x 120 run_ids = 1080 tests."""

    @pytest.mark.parametrize("repo,repo_name", REPO_VARIANTS)
    @pytest.mark.parametrize("run_id", RUN_IDS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_runid_cross(self, mock_get, mock_comp, mock_meta, repo, repo_name, run_id, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(repo=repo, instance_id=f"{repo.replace('/', '__')}-xrun")
            result = worker_function(datum, run_id)
        assert result["run_id"] == run_id
        assert result["instance_id"] == f"{repo.replace('/', '__')}-xrun"


class TestWorkerFileOutputExpanded:
    """Instance ID naming edge cases x run_ids subset = 50 x 5 = 250 tests."""

    _run_id_subset = RUN_IDS[:5]

    @pytest.mark.parametrize("instance_id", INSTANCE_ID_VARIANTS)
    @pytest.mark.parametrize("run_id", _run_id_subset)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_file_output_naming(self, mock_get, mock_comp, mock_meta, instance_id, run_id, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(instance_id=instance_id)
            result = worker_function(datum, run_id)
        assert result["instance_id"] == instance_id
        assert result["run_id"] == run_id
        output_file = tmp_path / run_id / f"{instance_id}.py"
        assert output_file.exists()


class TestWorkerLLMCallModels:
    """Parametrized model name tests = 20 tests."""

    @pytest.mark.parametrize("model_name", MODEL_VARIANTS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_model_name_passed(self, mock_get, mock_meta, model_name, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_MODEL", model_name)
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["model"] == model_name


class TestWorkerLLMCallApiBase:
    """Parametrized api_base tests = 20 tests."""

    @pytest.mark.parametrize("api_base", API_BASE_VARIANTS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_api_base_passed(self, mock_get, mock_meta, api_base, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_BEDROCK_RUNTIME_ENDPOINT", api_base)
        with (
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["api_base"] == api_base


class TestWorkerLLMCallMetadata:
    """Parametrized metadata tests = 10 tests."""

    @pytest.mark.parametrize("meta_dict", METADATA_VARIANTS, ids=[str(i) for i in range(len(METADATA_VARIANTS))])
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_metadata_variants(self, mock_get, meta_dict, tmp_path):
        with (
            patch(f"{MODULE}.helicone_metadata", return_value=meta_dict),
            patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK)) as mock_comp,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            worker_function(make_datum(), "run_001")
        assert mock_comp.call_args[1]["metadata"] == meta_dict


class TestWorkerGitHubFetchStatusCodes:
    """Parametrized status code retry tests = 20 tests."""

    @pytest.mark.parametrize("status_code", RETRY_STATUS_CODES)
    @patch(f"{MODULE}.time.sleep")
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    def test_retry_on_status_code(self, mock_comp, mock_meta, mock_sleep, status_code, tmp_path):
        def status_get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = status_code
            resp.text = "error"
            return resp

        with (
            patch(f"{MODULE}.requests.get", side_effect=status_get) as mock_get,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            datum = make_datum()
            result = worker_function(datum, "run_001")
        # All non-200 codes should trigger 3 attempts (max_retries)
        assert mock_get.call_count == 3
        assert result is not None


class TestWorkerCommitXPatch:
    """Cross-product: 50 commits x 10 patches (subset) = 500 tests."""

    _patch_subset = PATCH_VARIANTS[:10]

    @pytest.mark.parametrize("commit", COMMIT_HASHES)
    @pytest.mark.parametrize(
        "pname,diff_patch,expected_fetch_count",
        _patch_subset,
        ids=[p[0] for p in _patch_subset],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.completion", return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK))
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_commit_patch_cross(self, mock_get, mock_comp, mock_meta, commit, pname, diff_patch, expected_fetch_count, tmp_path):
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            datum = make_datum(base_commit=commit, patch=diff_patch)
            result = worker_function(datum, "run_001")
        assert result is not None
        assert mock_get.call_count == expected_fetch_count
        if expected_fetch_count > 0:
            url = mock_get.call_args[0][0]
            assert commit in url
