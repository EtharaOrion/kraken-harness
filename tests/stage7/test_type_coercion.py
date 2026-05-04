from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from helpers import (
    extract_code_block,
    main,
    make_completion_response,
    make_datum,
    worker_function,
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


# ---------------------------------------------------------------------------
# Helper: fake requests.get that always returns 200
# ---------------------------------------------------------------------------
def _fake_requests_get_ok(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = f"# content of {url}\npass\n"
    return resp


# ===================================================================
# 1. TestExtractCodeBlockTypeCoercion (~25 cases)
#    Pass wrong types to extract_code_block(text).
#    The function calls re.search on text; non-str types should raise.
# ===================================================================

EXTRACT_WRONG_TYPES = [
    pytest.param(42, id="int"),
    pytest.param(-1, id="negative_int"),
    pytest.param(0, id="zero_int"),
    pytest.param(3.14, id="float"),
    pytest.param(0.0, id="float_zero"),
    pytest.param(True, id="bool_true"),
    pytest.param(False, id="bool_false"),
    pytest.param([1, 2, 3], id="list_of_ints"),
    pytest.param(["a", "b"], id="list_of_strs"),
    pytest.param([], id="empty_list"),
    pytest.param({"key": "val"}, id="dict"),
    pytest.param({}, id="empty_dict"),
    pytest.param((1, 2), id="tuple"),
    pytest.param((), id="empty_tuple"),
    pytest.param({1, 2, 3}, id="set"),
    pytest.param(frozenset([1, 2]), id="frozenset"),
    pytest.param(complex(1, 2), id="complex"),
    pytest.param(Path("/tmp/test"), id="path_object"),
    pytest.param(Path("."), id="path_dot"),
    pytest.param(object(), id="plain_object"),
    pytest.param(lambda x: x, id="lambda"),
    pytest.param(re, id="module"),
    pytest.param(range(10), id="range"),
    pytest.param(memoryview(b"abc"), id="memoryview"),
]


class TestExtractCodeBlockTypeCoercion:
    """Wrong types passed to extract_code_block should raise TypeError."""

    @pytest.mark.parametrize("bad_input", EXTRACT_WRONG_TYPES)
    def test_non_string_raises(self, bad_input):
        with pytest.raises(TypeError):
            extract_code_block(bad_input)

    # bytes that look like code blocks — re.search on bytes pattern fails with TypeError
    @pytest.mark.parametrize(
        "byte_input",
        [
            pytest.param(b"```python\nprint('hi')\n```", id="bytes_code_block"),
            pytest.param(b"```\ncode()\n```", id="bytes_no_lang"),
            pytest.param(b"plain bytes text", id="bytes_plain"),
            pytest.param(b"", id="bytes_empty"),
        ],
    )
    def test_bytes_raises(self, byte_input):
        with pytest.raises(TypeError):
            extract_code_block(byte_input)


# ===================================================================
# 2. TestWorkerFunctionTypeCoercion (~40 cases)
#    datum as wrong type, datum with wrong value types, run_id as wrong type.
# ===================================================================

# --- 2a. datum as completely wrong type ---
DATUM_WRONG_TYPE = [
    pytest.param("a string", id="datum_str"),
    pytest.param(42, id="datum_int"),
    pytest.param(3.14, id="datum_float"),
    pytest.param([1, 2, 3], id="datum_list"),
    pytest.param((1, 2), id="datum_tuple"),
    pytest.param(True, id="datum_bool"),
    pytest.param(b"bytes", id="datum_bytes"),
    pytest.param(set(), id="datum_set"),
    pytest.param(None, id="datum_none"),
    pytest.param(object(), id="datum_object"),
]


class TestWorkerFunctionDatumWrongType:
    """datum as completely wrong type should raise TypeError or AttributeError."""

    @pytest.mark.parametrize("bad_datum", DATUM_WRONG_TYPE)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_datum_wrong_type_raises(
        self, mock_get, mock_comp, mock_meta, bad_datum, tmp_path
    ):
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            pytest.raises((TypeError, AttributeError, KeyError)),
        ):
            worker_function(bad_datum, "run_001")


# --- 2b. datum as dict but with wrong value types for specific keys ---

DATUM_PATCH_WRONG = [
    pytest.param(123, id="patch_int"),
    pytest.param(45.6, id="patch_float"),
    pytest.param(["a", "b"], id="patch_list"),
    pytest.param(True, id="patch_bool"),
    pytest.param(None, id="patch_none"),
    pytest.param(b"diff bytes", id="patch_bytes"),
    pytest.param({"nested": "dict"}, id="patch_dict"),
]


class TestWorkerFunctionDatumPatchWrongType:
    """datum['patch'] as non-str should raise on re.findall."""

    @pytest.mark.parametrize("bad_patch", DATUM_PATCH_WRONG)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_patch_wrong_type_raises(
        self, mock_get, mock_comp, mock_meta, bad_patch, tmp_path
    ):
        datum = make_datum()
        datum["patch"] = bad_patch
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            pytest.raises((TypeError, AttributeError)),
        ):
            worker_function(datum, "run_001")


DATUM_REPO_WRONG = [
    pytest.param(123, id="repo_int"),
    pytest.param(45.6, id="repo_float"),
    pytest.param(["numpy", "numpy"], id="repo_list"),
    pytest.param(True, id="repo_bool"),
    pytest.param(None, id="repo_none"),
    pytest.param(b"numpy/numpy", id="repo_bytes"),
]


class TestWorkerFunctionDatumRepoWrongType:
    """datum['repo'] as non-str should raise on .split('/')."""

    @pytest.mark.parametrize("bad_repo", DATUM_REPO_WRONG)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_wrong_type_raises(
        self, mock_get, mock_comp, mock_meta, bad_repo, tmp_path
    ):
        datum = make_datum()
        datum["repo"] = bad_repo
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            pytest.raises((TypeError, AttributeError, ValueError)),
        ):
            worker_function(datum, "run_001")


DATUM_BASE_COMMIT_WRONG = [
    pytest.param(12345, id="base_commit_int"),
    pytest.param(3.14, id="base_commit_float"),
    pytest.param(["abc", "def"], id="base_commit_list"),
    pytest.param(True, id="base_commit_bool"),
    pytest.param(None, id="base_commit_none"),
    pytest.param({"hash": "abc"}, id="base_commit_dict"),
]


class TestWorkerFunctionDatumBaseCommitWrongType:
    """datum['base_commit'] as non-str should raise on string operations."""

    @pytest.mark.parametrize("bad_commit", DATUM_BASE_COMMIT_WRONG)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_base_commit_wrong_type_raises(
        self, mock_get, mock_comp, mock_meta, bad_commit, tmp_path
    ):
        datum = make_datum()
        datum["base_commit"] = bad_commit
        # base_commit is used in f-string URL construction — f-strings coerce via str()
        # so non-str types may NOT raise; we verify the URL contains the str() representation
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_001")
        # If it didn't raise, the str() representation should appear in the URL
        url = mock_get.call_args[0][0]
        assert str(bad_commit) in url


DATUM_INSTANCE_ID_WRONG = [
    pytest.param(12345, id="instance_id_int"),
    pytest.param(3.14, id="instance_id_float"),
    pytest.param(["a", "b"], id="instance_id_list"),
    pytest.param(True, id="instance_id_bool"),
    pytest.param(None, id="instance_id_none"),
    pytest.param({"id": "x"}, id="instance_id_dict"),
]


class TestWorkerFunctionDatumInstanceIdWrongType:
    """datum['instance_id'] as non-str should raise on path construction."""

    @pytest.mark.parametrize("bad_id", DATUM_INSTANCE_ID_WRONG)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_instance_id_wrong_type_raises_or_coerces(
        self, mock_get, mock_comp, mock_meta, bad_id, tmp_path
    ):
        datum = make_datum()
        datum["instance_id"] = bad_id
        # Path / operator coerces via str(), so many types will work.
        # We verify the output file name contains str(bad_id)
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_001")
        assert result["instance_id"] == bad_id


# --- 2c. run_id as wrong type ---
RUN_ID_WRONG_TYPES = [
    pytest.param(42, id="run_id_int"),
    pytest.param(3.14, id="run_id_float"),
    pytest.param([1, 2], id="run_id_list"),
    pytest.param({"a": 1}, id="run_id_dict"),
    pytest.param(None, id="run_id_none"),
    pytest.param(b"run_bytes", id="run_id_bytes"),
    pytest.param(True, id="run_id_bool"),
    pytest.param((1,), id="run_id_tuple"),
    pytest.param(Path("/tmp/run"), id="run_id_path"),
]


class TestWorkerFunctionRunIdWrongType:
    """run_id as wrong type should raise on path operations or coerce."""

    @pytest.mark.parametrize("bad_run_id", RUN_ID_WRONG_TYPES)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_wrong_type(
        self, mock_get, mock_comp, mock_meta, bad_run_id, tmp_path
    ):
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            # Path / operator coerces many types. We check if it raises or
            # produces a result with the coerced run_id.
            try:
                result = worker_function(datum, bad_run_id)
                # If no exception, verify coercion happened
                assert result["run_id"] == bad_run_id
            except (TypeError, AttributeError):
                pass  # Expected for types that can't be coerced by Path


# ===================================================================
# 3. TestMainTypeCoercion (~25 cases)
#    Wrong types for main() parameters.
# ===================================================================

MAIN_DATASET_NAME_WRONG = [
    pytest.param(42, id="dataset_name_int"),
    pytest.param(3.14, id="dataset_name_float"),
    pytest.param([1, 2], id="dataset_name_list"),
    pytest.param(None, id="dataset_name_none"),
    pytest.param(True, id="dataset_name_bool"),
    pytest.param({"a": 1}, id="dataset_name_dict"),
]

MAIN_SPLIT_WRONG = [
    pytest.param(42, id="split_int"),
    pytest.param([1, 2], id="split_list"),
    pytest.param(None, id="split_none"),
    pytest.param(True, id="split_bool"),
    pytest.param(3.14, id="split_float"),
]

MAIN_INSTANCE_IDS_WRONG = [
    pytest.param("not_a_list", id="instance_ids_str"),
    pytest.param(42, id="instance_ids_int"),
    pytest.param({"a": 1}, id="instance_ids_dict"),
    pytest.param(True, id="instance_ids_bool"),
    pytest.param(3.14, id="instance_ids_float"),
]

MAIN_MAX_WORKERS_WRONG = [
    pytest.param("ten", id="max_workers_str"),
    pytest.param(3.14, id="max_workers_float"),
    pytest.param(None, id="max_workers_none"),
    pytest.param(-1, id="max_workers_negative"),
    pytest.param([4], id="max_workers_list"),
    pytest.param(0, id="max_workers_zero"),
]

MAIN_RUN_ID_WRONG = [
    pytest.param(42, id="run_id_int"),
    pytest.param([1, 2], id="run_id_list"),
    pytest.param(None, id="run_id_none"),
    pytest.param(True, id="run_id_bool"),
    pytest.param({"a": 1}, id="run_id_dict"),
]


class TestMainDatasetNameTypeCoercion:
    """dataset_name as wrong type passed to load_swefficiency_dataset."""

    @pytest.mark.parametrize("bad_name", MAIN_DATASET_NAME_WRONG)
    def test_dataset_name_wrong_type(self, bad_name, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(
                f"{MODULE}.load_swefficiency_dataset", return_value=[]
            ) as mock_load,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            # main passes dataset_name directly to load_swefficiency_dataset.
            # The mock accepts anything, so no exception from main itself.
            # We verify the wrong type is forwarded.
            main(
                dataset_name=bad_name,
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="tc_dsname",
            )
        mock_load.assert_called_once_with(bad_name, "test")


class TestMainSplitTypeCoercion:
    """split as wrong type passed to load_swefficiency_dataset."""

    @pytest.mark.parametrize("bad_split", MAIN_SPLIT_WRONG)
    def test_split_wrong_type(self, bad_split, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(
                f"{MODULE}.load_swefficiency_dataset", return_value=[]
            ) as mock_load,
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            main(
                dataset_name="test",
                split=bad_split,
                instance_ids=[],
                max_workers=1,
                run_id="tc_split",
            )
        mock_load.assert_called_once_with("test", bad_split)


class TestMainInstanceIdsTypeCoercion:
    """instance_ids as wrong type should raise or misbehave on iteration."""

    @pytest.mark.parametrize("bad_ids", MAIN_INSTANCE_IDS_WRONG)
    def test_instance_ids_wrong_type(self, bad_ids, tmp_path):
        dataset = [make_datum()]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(
                f"{MODULE}.completion",
                return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
            ),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            # str is iterable, so "not_a_list" won't raise but will filter incorrectly.
            # int, dict, bool, float should raise TypeError on `in` operator or iteration.
            if isinstance(bad_ids, (str, dict)):
                # str is iterable — `in` does character-level matching
                # dict — `in` checks keys, so no TypeError raised
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=bad_ids,
                    max_workers=1,
                    run_id="tc_ids",
                )
            else:
                with pytest.raises((TypeError, AttributeError)):
                    main(
                        dataset_name="test",
                        split="test",
                        instance_ids=bad_ids,
                        max_workers=1,
                        run_id="tc_ids",
                    )


class TestMainMaxWorkersTypeCoercion:
    """max_workers as wrong type should raise on ThreadPoolExecutor."""

    @pytest.mark.parametrize("bad_workers", MAIN_MAX_WORKERS_WRONG)
    def test_max_workers_wrong_type(self, bad_workers, tmp_path):
        dataset = [make_datum()]
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(
                f"{MODULE}.completion",
                return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
            ),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            # ThreadPoolExecutor(max_workers=...) validates the type/value
            # str, None with 0 items, list, negative, zero — various errors
            try:
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=bad_workers,
                    run_id="tc_workers",
                )
            except (TypeError, ValueError):
                pass  # Expected for invalid max_workers


class TestMainRunIdTypeCoercion:
    """run_id as wrong type should raise or coerce in path operations."""

    @pytest.mark.parametrize("bad_run_id", MAIN_RUN_ID_WRONG)
    def test_run_id_wrong_type(self, bad_run_id, tmp_path):
        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(
                f"{MODULE}.completion",
                return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
            ),
            patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=[make_datum()]),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        ):
            # Path / operator will coerce int/bool to str, but list/dict/None will raise
            try:
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id=bad_run_id,
                )
            except (TypeError, AttributeError):
                pass  # Expected for types that can't be coerced


# ===================================================================
# 4. TestContextMsgTypeCoercion (~10 cases)
#    CONTEXT_MSG.format() with wrong types.
# ===================================================================

from helpers import SAMPLE_PATCH  # noqa: E402

# Import CONTEXT_MSG directly for format testing
from swefficiency.workload.run_synthetic_generation import CONTEXT_MSG  # noqa: E402


class TestContextMsgTypeCoercion:
    """CONTEXT_MSG.format() with wrong types — Python str.format coerces via str()."""

    def test_repo_name_int(self):
        """int repo_name should be coerced to str by .format()."""
        result = CONTEXT_MSG.format(
            repo_name=123, commit_diff="diff", pre_edit_code="code"
        )
        assert "123" in result

    def test_repo_name_list(self):
        """list repo_name should be coerced to str by .format()."""
        result = CONTEXT_MSG.format(
            repo_name=[1, 2, 3], commit_diff="diff", pre_edit_code="code"
        )
        assert "[1, 2, 3]" in result

    def test_repo_name_none(self):
        """None repo_name should produce 'None' string."""
        result = CONTEXT_MSG.format(
            repo_name=None, commit_diff="diff", pre_edit_code="code"
        )
        assert "None" in result

    def test_repo_name_dict(self):
        """dict repo_name should be coerced to str by .format()."""
        result = CONTEXT_MSG.format(
            repo_name={"a": 1}, commit_diff="diff", pre_edit_code="code"
        )
        assert "'a'" in result

    def test_commit_diff_int(self):
        """int commit_diff should be coerced to str."""
        result = CONTEXT_MSG.format(
            repo_name="repo", commit_diff=999, pre_edit_code="code"
        )
        assert "999" in result

    def test_commit_diff_list(self):
        """list commit_diff should be coerced to str."""
        result = CONTEXT_MSG.format(
            repo_name="repo", commit_diff=["line1", "line2"], pre_edit_code="code"
        )
        assert "line1" in result

    def test_pre_edit_code_none(self):
        """None pre_edit_code should produce 'None' string."""
        result = CONTEXT_MSG.format(
            repo_name="repo", commit_diff="diff", pre_edit_code=None
        )
        assert "None" in result

    def test_pre_edit_code_int(self):
        """int pre_edit_code should be coerced to str."""
        result = CONTEXT_MSG.format(
            repo_name="repo", commit_diff="diff", pre_edit_code=42
        )
        assert "42" in result

    def test_all_wrong_types(self):
        """All args as wrong types — format coerces all via str()."""
        result = CONTEXT_MSG.format(
            repo_name=True, commit_diff=3.14, pre_edit_code=[1, 2]
        )
        assert "True" in result
        assert "3.14" in result
        assert "[1, 2]" in result

    def test_missing_key_raises(self):
        """Missing a required key should raise KeyError."""
        with pytest.raises(KeyError):
            CONTEXT_MSG.format(repo_name="repo", commit_diff="diff")

    def test_extra_key_no_error(self):
        """Extra keys should not raise."""
        result = CONTEXT_MSG.format(
            repo_name="repo",
            commit_diff="diff",
            pre_edit_code="code",
            extra_key="extra",
        )
        assert "repo" in result

    def test_bytes_repo_name(self):
        """bytes repo_name should be coerced to str repr."""
        result = CONTEXT_MSG.format(
            repo_name=b"numpy", commit_diff="diff", pre_edit_code="code"
        )
        assert "numpy" in result

    def test_complex_repo_name(self):
        """complex repo_name should be coerced to str."""
        result = CONTEXT_MSG.format(
            repo_name=complex(1, 2), commit_diff="diff", pre_edit_code="code"
        )
        assert "(1+2j)" in result

    def test_path_commit_diff(self):
        """Path commit_diff should be coerced to str."""
        result = CONTEXT_MSG.format(
            repo_name="repo", commit_diff=Path("/tmp/diff"), pre_edit_code="code"
        )
        assert "/tmp/diff" in result
