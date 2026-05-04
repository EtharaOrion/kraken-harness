from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from helpers import (
    SAMPLE_CODE_BLOCK,
    SAMPLE_LLM_RESPONSE_NO_BLOCK,
    SAMPLE_LLM_RESPONSE_WITH_BLOCK,
    SAMPLE_PATCH,
    extract_code_block,
    make_completion_response,
    make_datum,
    main,
    worker_function,
    WORKLOAD_GENERATION_DIR,
)

MODULE = "swefficiency.workload.run_synthetic_generation"


def _fake_requests_get_ok(url: str, *args: Any, **kwargs: Any) -> MagicMock:
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


REQUIRED_DATUM_KEYS = ["patch", "repo", "base_commit", "instance_id"]


class TestWorkerMissingDatumKeys:

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_dict_raises_key_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError):
                worker_function({}, "run_null")

    @pytest.mark.parametrize("missing_key", REQUIRED_DATUM_KEYS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_single_missing_key_raises(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        missing_key: str,
    ) -> None:
        datum = make_datum()
        del datum[missing_key]
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError, match=re.escape(missing_key)):
                worker_function(datum, "run_null")

    @pytest.mark.parametrize(
        "keys_to_remove",
        list(combinations(REQUIRED_DATUM_KEYS, 2)),
        ids=[f"missing_{'_and_'.join(k)}" for k in combinations(REQUIRED_DATUM_KEYS, 2)],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_two_missing_keys_raises(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        keys_to_remove: tuple[str, ...],
    ) -> None:
        datum = make_datum()
        for key in keys_to_remove:
            del datum[key]
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError):
                worker_function(datum, "run_null")

    @pytest.mark.parametrize(
        "keys_to_remove",
        list(combinations(REQUIRED_DATUM_KEYS, 3)),
        ids=[f"missing_{'_and_'.join(k)}" for k in combinations(REQUIRED_DATUM_KEYS, 3)],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_three_missing_keys_raises(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        keys_to_remove: tuple[str, ...],
    ) -> None:
        datum = make_datum()
        for key in keys_to_remove:
            del datum[key]
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError):
                worker_function(datum, "run_null")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_all_keys_missing_raises(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError):
                worker_function({}, "run_null")

    @pytest.mark.parametrize("missing_key", REQUIRED_DATUM_KEYS)
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_missing_key_with_extra_fields_still_raises(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        missing_key: str,
    ) -> None:
        datum = make_datum(extra_field="value", another_field=42)
        del datum[missing_key]
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(KeyError, match=re.escape(missing_key)):
                worker_function(datum, "run_null")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_datum_none_raises_type_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(TypeError):
                worker_function(None, "run_null")  # type: ignore[arg-type]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_datum_list_raises_type_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises((TypeError, KeyError)):
                worker_function([], "run_null")  # type: ignore[arg-type]


class TestWorkerEmptyDatumValues:

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_patch_no_diff_files(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        datum["patch"] = ""
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_empty")
        mock_get.assert_not_called()
        assert result["instance_id"] == datum["instance_id"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_repo_split_behavior(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(repo="")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            # "".split("/") => [""] — unpacking owner, repo raises ValueError
            with pytest.raises(ValueError):
                worker_function(datum, "run_empty")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_base_commit(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(base_commit="")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_empty")
        assert result["instance_id"] == datum["instance_id"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_instance_id_file_still_created(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(instance_id="")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_empty")
        assert result["instance_id"] == ""
        output_file = tmp_path / "run_empty" / ".py"
        assert output_file.exists()

    @pytest.mark.parametrize(
        "field",
        ["patch"],
        ids=["none_patch"],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_value_raises_type_error(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        field: str,
    ) -> None:
        kwargs = {field: None}
        if field == "patch":
            kwargs["patch"] = None
            datum = make_datum(**{k: v for k, v in kwargs.items()})
            datum["patch"] = None
        else:
            datum = make_datum(**kwargs)
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(TypeError):
                worker_function(datum, "run_none")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_base_commit_coerced_to_string(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(base_commit=None)
        datum["base_commit"] = None
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_none_commit")
        assert result["instance_id"] == datum["instance_id"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_instance_id_coerced_to_string(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(instance_id=None)
        datum["instance_id"] = None
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_none_id")
        assert result["instance_id"] is None

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_repo_raises_attribute_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(repo=None)  # type: ignore[arg-type]
        datum["repo"] = None
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(AttributeError):
                worker_function(datum, "run_none")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_only_patch(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(patch="   \n\t  ")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_ws")
        mock_get.assert_not_called()
        assert result["instance_id"] == datum["instance_id"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_only_repo_raises(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(repo="  ")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            # "  ".split("/") => ["  "] — not enough values to unpack
            with pytest.raises(ValueError):
                worker_function(datum, "run_ws")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_only_base_commit(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(base_commit="   ")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_ws")
        assert result["instance_id"] == datum["instance_id"]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_only_instance_id(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(instance_id="   ")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_ws")
        assert result["instance_id"] == "   "

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_single_segment_no_slash_raises(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(repo="noslash")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(ValueError):
                worker_function(datum, "run_noslash")

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_repo_too_many_slashes(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum(repo="a/b/c/d")
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(ValueError):
                worker_function(datum, "run_manyslash")

    @pytest.mark.parametrize(
        "empty_combo",
        [
            {"patch": "", "base_commit": ""},
            {"patch": "", "instance_id": ""},
            {"base_commit": "", "instance_id": ""},
        ],
        ids=["empty_patch_and_commit", "empty_patch_and_id", "empty_commit_and_id"],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_multiple_empty_values(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        empty_combo: dict[str, str],
    ) -> None:
        datum = make_datum(**empty_combo)
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_multi_empty")
        assert result["instance_id"] == datum["instance_id"]


class TestWorkerNullRunId:

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_none_run_id_raises_type_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(TypeError):
                worker_function(datum, None)  # type: ignore[arg-type]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_run_id(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "")
        assert result["run_id"] == ""
        output_file = tmp_path / "" / f"{datum['instance_id']}.py"
        assert output_file.exists()

    @pytest.mark.parametrize(
        "ws_run_id",
        [" ", "  ", "\t", "\n", " \t\n "],
        ids=["space", "double_space", "tab", "newline", "mixed_ws"],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_run_id(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        ws_run_id: str,
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, ws_run_id)
        assert result["run_id"] == ws_run_id

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_with_slashes(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "a/b/c")
        assert result["run_id"] == "a/b/c"
        output_file = tmp_path / "a" / "b" / "c" / f"{datum['instance_id']}.py"
        assert output_file.exists()

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_with_dots(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run..test")
        assert result["run_id"] == "run..test"

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_int_raises_type_error(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(TypeError):
                worker_function(datum, 123)  # type: ignore[arg-type]

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_run_id_special_chars(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run-test_v2.0")
        assert result["run_id"] == "run-test_v2.0"


class TestMainEmptyDataset:

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_no_crash(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="run_empty",
            )
        output_path = tmp_path / "run_empty" / "workload_generation.json"
        assert output_path.exists()
        assert output_path.read_text() == ""

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_with_instance_ids_filter(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=["nonexistent_id"],
                max_workers=1,
                run_id="run_filtered",
            )
        output_path = tmp_path / "run_filtered" / "workload_generation.json"
        assert output_path.exists()
        assert output_path.read_text() == ""

    @patch(f"{MODULE}.setup_helicone")
    @patch(
        f"{MODULE}.load_swefficiency_dataset",
        return_value=_make_dataset(3),
    )
    def test_instance_ids_matches_nothing(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=["zzzz_nonexistent"],
                max_workers=1,
                run_id="run_no_match",
            )
        output_path = tmp_path / "run_no_match" / "workload_generation.json"
        assert output_path.exists()
        assert output_path.read_text() == ""

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    @patch(f"{MODULE}.setup_helicone")
    @patch(
        f"{MODULE}.load_swefficiency_dataset",
        return_value=_make_dataset(3),
    )
    def test_none_instance_ids_processes_all(
        self,
        mock_load: MagicMock,
        mock_helicone: MagicMock,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="run_all",
            )
        output_path = tmp_path / "run_all" / "workload_generation.json"
        lines = [ln for ln in output_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 3

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(3))
    def test_empty_list_instance_ids(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "test",
                    "run_id": "run_emptylist",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[],
                    max_workers=1,
                    run_id="run_emptylist",
                )
                assert mock_worker.call_count == 3

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(5))
    def test_instance_ids_partial_match(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "numpy__numpy-0",
                    "run_id": "run_partial",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=["numpy__numpy-0", "NONEXISTENT"],
                    max_workers=1,
                    run_id="run_partial",
                )
                assert mock_worker.call_count == 1

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_empty_run_id(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="",
            )
        output_path = tmp_path / "" / "workload_generation.json"
        assert output_path.exists()

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_max_workers_zero(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(ValueError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=None,
                    max_workers=0,
                    run_id="run_zero",
                )

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_negative_workers(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(ValueError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=None,
                    max_workers=-1,
                    run_id="run_neg",
                )

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(2))
    def test_instance_ids_with_none_elements(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "test",
                    "run_id": "run_none_elem",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[None, "numpy__numpy-0"],  # type: ignore[list-item]
                    max_workers=1,
                    run_id="run_none_elem",
                )
                assert mock_worker.call_count == 1

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(2))
    def test_instance_ids_all_empty_strings(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "test",
                    "run_id": "run_empty_ids",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=["", "", ""],
                    max_workers=1,
                    run_id="run_empty_ids",
                )
                assert mock_worker.call_count == 0

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(3))
    def test_duplicate_instance_ids(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "numpy__numpy-0",
                    "run_id": "run_dup",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=["numpy__numpy-0", "numpy__numpy-0"],
                    max_workers=1,
                    run_id="run_dup",
                )
                assert mock_worker.call_count == 1


EMPTY_BLOCK_CASES = [
    ("empty_fenced_no_lang", "```\n```", None),
    ("empty_fenced_python", "```python\n```", None),
    ("whitespace_only_block", "```python\n   \n   \n```", None),
    ("newlines_only_block", "```python\n\n\n\n```", None),
    ("tabs_only_block", "```python\n\t\t\t\n```", None),
    ("single_newline_block", "```\n\n```", None),
    ("block_with_only_spaces", "```\n     \n```", None),
    ("block_mixed_ws_only", "```python\n \t \n \t \n```", None),
]


class TestExtractCodeBlockNullEmpty:

    @pytest.mark.parametrize(
        "name,text,expected",
        EMPTY_BLOCK_CASES,
        ids=[c[0] for c in EMPTY_BLOCK_CASES],
    )
    def test_empty_block_returns_none_or_empty(
        self, name: str, text: str, expected: str | None
    ) -> None:
        result = extract_code_block(text)
        assert result == "" or result is None

    def test_none_input(self) -> None:
        assert extract_code_block(None) is None

    def test_empty_string_input(self) -> None:
        assert extract_code_block("") is None

    def test_whitespace_only_input(self) -> None:
        assert extract_code_block("   \n\t  ") is None

    def test_multiple_empty_blocks(self) -> None:
        text = "```python\n```\nsome text\n```python\n```"
        result = extract_code_block(text)
        assert result == "" or result is None

    def test_block_with_only_comment(self) -> None:
        text = "```python\n# just a comment\n```"
        result = extract_code_block(text)
        assert result is not None
        assert "# just a comment" in result

    def test_block_with_empty_string_literal(self) -> None:
        text = '```python\nx = ""\n```'
        result = extract_code_block(text)
        assert result is not None
        assert 'x = ""' in result

    def test_block_with_none_literal(self) -> None:
        text = "```python\nx = None\n```"
        result = extract_code_block(text)
        assert result is not None
        assert "x = None" in result

    def test_backticks_only(self) -> None:
        assert extract_code_block("```") is None

    def test_six_backticks_no_content(self) -> None:
        assert extract_code_block("``````") is None

    def test_nested_backtick_blocks(self) -> None:
        text = "````python\n```\ninner\n```\n````"
        result = extract_code_block(text)
        assert result is not None or result is None

    def test_unclosed_block_no_match(self) -> None:
        assert extract_code_block("```python\ncode()") is None

    def test_closing_only_no_match(self) -> None:
        assert extract_code_block("some text\n```") is None


class TestWorkerCompletionReturnsEmpty:

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(""),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_completion_content(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_empty_llm")
        assert result["workload"] == ""

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response("No code here."),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_no_block_completion(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_no_block")
        assert result["workload"] == "No code here."

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response("   \n\t  "),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_only_completion(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_ws_llm")
        assert result["workload"] == "   \n\t  "

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_completion_none_content(
        self, mock_get: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        resp = make_completion_response("dummy")
        resp.choices[0].message.content = None
        with patch(f"{MODULE}.completion", return_value=resp):
            datum = make_datum()
            with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
                result = worker_function(datum, "run_none_content")
        assert result["workload"] is None

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response("```\n```"),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_code_block_in_completion(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_empty_block")
        output_file = tmp_path / "run_empty_block" / f"{datum['instance_id']}.py"
        assert output_file.exists()

    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response("```python\n   \n```"),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_whitespace_code_block_in_completion(
        self, mock_get: MagicMock, mock_comp: MagicMock, mock_meta: MagicMock, tmp_path: Path
    ) -> None:
        datum = make_datum()
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, "run_ws_block")
        output_file = tmp_path / "run_ws_block" / f"{datum['instance_id']}.py"
        assert output_file.exists()


_NULL_COMBOS = [
    ({"patch": ""}, "empty_patch_only"),
    ({"instance_id": ""}, "empty_id_only"),
    ({"base_commit": ""}, "empty_commit_only"),
    ({"patch": "", "instance_id": ""}, "empty_patch_and_id"),
    ({"patch": "", "base_commit": ""}, "empty_patch_and_commit"),
    ({"instance_id": "", "base_commit": ""}, "empty_id_and_commit"),
    ({"patch": "", "instance_id": "", "base_commit": ""}, "all_three_empty"),
]


class TestWorkerNullCombinations:

    @pytest.mark.parametrize(
        "overrides,label",
        _NULL_COMBOS,
        ids=[c[1] for c in _NULL_COMBOS],
    )
    @patch(f"{MODULE}.helicone_metadata", return_value={})
    @patch(
        f"{MODULE}.completion",
        return_value=make_completion_response(SAMPLE_LLM_RESPONSE_WITH_BLOCK),
    )
    @patch(f"{MODULE}.requests.get", side_effect=_fake_requests_get_ok)
    def test_empty_combo_no_crash(
        self,
        mock_get: MagicMock,
        mock_comp: MagicMock,
        mock_meta: MagicMock,
        tmp_path: Path,
        overrides: dict[str, str],
        label: str,
    ) -> None:
        datum = make_datum(**overrides)
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            result = worker_function(datum, f"run_{label}")
        assert "instance_id" in result
        assert "run_id" in result
        assert "workload" in result


class TestMainNullArguments:

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_none_run_id(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with pytest.raises(TypeError):
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=None,
                    max_workers=1,
                    run_id=None,  # type: ignore[arg-type]
                )

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_dataset_name(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="",
                split="test",
                instance_ids=None,
                max_workers=1,
                run_id="run_empty_ds",
            )
        mock_load.assert_called_once_with("", "test")

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_empty_split(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="",
                instance_ids=None,
                max_workers=1,
                run_id="run_empty_split",
            )
        mock_load.assert_called_once_with("test", "")

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(1))
    def test_instance_ids_whitespace_only_entries(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "test",
                    "run_id": "run_ws_ids",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=["  ", "\t", "\n"],
                    max_workers=1,
                    run_id="run_ws_ids",
                )
                assert mock_worker.call_count == 0

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=_make_dataset(2))
    def test_single_none_in_instance_ids(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            with patch(f"{MODULE}.worker_function") as mock_worker:
                mock_worker.return_value = {
                    "instance_id": "test",
                    "run_id": "run_single_none",
                    "workload": "code",
                }
                main(
                    dataset_name="test",
                    split="test",
                    instance_ids=[None],  # type: ignore[list-item]
                    max_workers=1,
                    run_id="run_single_none",
                )
                assert mock_worker.call_count == 0

    @patch(f"{MODULE}.setup_helicone")
    @patch(f"{MODULE}.load_swefficiency_dataset", return_value=[])
    def test_none_max_workers(
        self, mock_load: MagicMock, mock_helicone: MagicMock, tmp_path: Path
    ) -> None:
        with patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path):
            main(
                dataset_name="test",
                split="test",
                instance_ids=None,
                max_workers=None,  # type: ignore[arg-type]
                run_id="run_none_workers",
            )
        output_path = tmp_path / "run_none_workers" / "workload_generation.json"
        assert output_path.exists()
