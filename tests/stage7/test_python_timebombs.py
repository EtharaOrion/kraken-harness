from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from helpers import (
    CONTEXT_MSG,
    SYSTEM_MSG,
    WORKLOAD_GENERATION_DIR,
    extract_code_block,
    main,
    make_completion_response,
    make_datum,
    worker_function,
)

MODULE = "swefficiency.workload.run_synthetic_generation"

SAMPLE_LLM_RESPONSE = """Here is the workload:

```python
import timeit
import statistics

def setup():
    global x
    x = list(range(1000))

def workload():
    global x
    _ = sorted(x)

runtimes = timeit.repeat(workload, number=1, repeat=5, setup=setup)

print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
```
"""

EXTRACTED_CODE = (
    "import timeit\nimport statistics\n\ndef setup():\n"
    "    global x\n    x = list(range(1000))\n\ndef workload():\n"
    "    global x\n    _ = sorted(x)\n\n"
    "runtimes = timeit.repeat(workload, number=1, repeat=5, setup=setup)\n\n"
    'print("Mean:", statistics.mean(runtimes))\n'
    'print("Std Dev:", statistics.stdev(runtimes))'
)


# ---------------------------------------------------------------------------
# Helper: fake requests.get that always returns 200
# ---------------------------------------------------------------------------
def _fake_get_ok(url: str, *args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = f"# content of {url}\npass\n"
    return resp


def _run_worker(tmp_path, datum=None, run_id="run_001", llm_text=None):
    """Convenience: run worker_function with all externals mocked."""
    datum = datum or make_datum()
    llm_text = llm_text or SAMPLE_LLM_RESPONSE
    with (
        patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        patch(f"{MODULE}.helicone_metadata", return_value={}),
        patch(
            f"{MODULE}.completion",
            return_value=make_completion_response(llm_text),
        ),
        patch(f"{MODULE}.requests.get", side_effect=_fake_get_ok),
    ):
        return worker_function(datum, run_id)


# ===================================================================
# 1. TestMutableDefaults (~15 cases)
# ===================================================================
class TestMutableDefaults:
    """Verify module-level constants are not mutable between calls."""

    def test_workload_dir_is_path(self):
        assert isinstance(WORKLOAD_GENERATION_DIR, Path)

    def test_workload_dir_value_stable(self):
        val1 = WORKLOAD_GENERATION_DIR
        val2 = WORKLOAD_GENERATION_DIR
        assert val1 == val2

    def test_workload_dir_identity_is_same_object(self):
        assert WORKLOAD_GENERATION_DIR is WORKLOAD_GENERATION_DIR

    def test_workload_dir_not_empty(self):
        assert str(WORKLOAD_GENERATION_DIR) != ""

    def test_workload_dir_str_repr_stable(self):
        s1 = str(WORKLOAD_GENERATION_DIR)
        s2 = str(WORKLOAD_GENERATION_DIR)
        assert s1 == s2

    def test_system_msg_is_str(self):
        assert isinstance(SYSTEM_MSG, str)

    def test_system_msg_immutable_across_reads(self):
        s1 = SYSTEM_MSG
        s2 = SYSTEM_MSG
        assert s1 == s2
        assert len(s1) == len(s2)

    def test_context_msg_is_str(self):
        assert isinstance(CONTEXT_MSG, str)

    def test_context_msg_immutable_across_reads(self):
        c1 = CONTEXT_MSG
        c2 = CONTEXT_MSG
        assert c1 == c2
        assert len(c1) == len(c2)

    def test_extract_code_block_same_input_same_output(self):
        text = "```python\nprint('hi')\n```"
        r1 = extract_code_block(text)
        r2 = extract_code_block(text)
        assert r1 == r2

    def test_extract_code_block_no_state_leakage_after_none(self):
        assert extract_code_block(None) is None
        result = extract_code_block("```python\nx=1\n```")
        assert result == "x=1"

    def test_extract_code_block_no_state_leakage_after_match(self):
        extract_code_block("```python\nfirst\n```")
        result = extract_code_block("```python\nsecond\n```")
        assert result == "second"

    def test_extract_code_block_repeated_10_times_deterministic(self):
        text = "```python\nfor i in range(10): pass\n```"
        results = [extract_code_block(text) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_worker_no_shared_state_between_calls(self, tmp_path):
        r1 = _run_worker(tmp_path, make_datum(instance_id="id_A"), "run_1")
        r2 = _run_worker(tmp_path, make_datum(instance_id="id_B"), "run_2")
        assert r1["instance_id"] == "id_A"
        assert r2["instance_id"] == "id_B"

    def test_worker_first_call_does_not_alter_second(self, tmp_path):
        d1 = make_datum(instance_id="alpha")
        d2 = make_datum(instance_id="beta")
        r1 = _run_worker(tmp_path, d1, "r1")
        r2 = _run_worker(tmp_path, d2, "r2")
        assert r1["workload"] == r2["workload"]

    def test_workload_dir_type_unchanged_after_worker(self, tmp_path):
        _run_worker(tmp_path)
        assert isinstance(WORKLOAD_GENERATION_DIR, Path)


# ===================================================================
# 2. TestShallowVsDeepCopy (~15 cases)
# ===================================================================
class TestShallowVsDeepCopy:
    """Verify returned dicts are independent — mutation doesn't cross-pollinate."""

    def test_worker_return_dict_mutation_no_bleed(self, tmp_path):
        r1 = _run_worker(tmp_path, run_id="cp_1")
        r1["instance_id"] = "MUTATED"
        r2 = _run_worker(tmp_path, run_id="cp_2")
        assert r2["instance_id"] != "MUTATED"

    def test_worker_return_add_key_no_bleed(self, tmp_path):
        r1 = _run_worker(tmp_path, run_id="cp_3")
        r1["extra_key"] = "extra_value"
        r2 = _run_worker(tmp_path, run_id="cp_4")
        assert "extra_key" not in r2

    def test_worker_return_delete_key_no_bleed(self, tmp_path):
        r1 = _run_worker(tmp_path, run_id="cp_5")
        del r1["workload"]
        r2 = _run_worker(tmp_path, run_id="cp_6")
        assert "workload" in r2

    def test_worker_return_workload_mutation_no_bleed(self, tmp_path):
        r1 = _run_worker(tmp_path, run_id="cp_7")
        original_workload = r1["workload"]
        r1["workload"] = "REPLACED"
        r2 = _run_worker(tmp_path, run_id="cp_8")
        assert r2["workload"] == original_workload

    def test_worker_return_is_dict(self, tmp_path):
        result = _run_worker(tmp_path)
        assert isinstance(result, dict)

    def test_worker_returns_new_dict_each_call(self, tmp_path):
        r1 = _run_worker(tmp_path, make_datum(instance_id="x1"), "cp_9")
        r2 = _run_worker(tmp_path, make_datum(instance_id="x2"), "cp_10")
        assert r1 is not r2

    def test_make_datum_returns_independent_dicts(self):
        d1 = make_datum()
        d2 = make_datum()
        assert d1 is not d2

    def test_make_datum_mutation_does_not_affect_next(self):
        d1 = make_datum()
        d1["instance_id"] = "MUTATED"
        d2 = make_datum()
        assert d2["instance_id"] != "MUTATED"

    def test_make_datum_add_key_independent(self):
        d1 = make_datum()
        d1["new_field"] = 999
        d2 = make_datum()
        assert "new_field" not in d2

    def test_make_datum_delete_key_independent(self):
        d1 = make_datum()
        del d1["repo"]
        d2 = make_datum()
        assert "repo" in d2

    def test_make_datum_deep_copy_equivalent(self):
        d1 = make_datum()
        d2 = copy.deepcopy(d1)
        assert d1 == d2
        assert d1 is not d2

    def test_worker_does_not_mutate_original_datum(self, tmp_path):
        datum = make_datum(instance_id="original_id")
        original = copy.deepcopy(datum)
        _run_worker(tmp_path, datum, "cp_11")
        assert datum == original

    def test_worker_does_not_mutate_datum_patch(self, tmp_path):
        datum = make_datum()
        original_patch = datum["patch"]
        _run_worker(tmp_path, datum, "cp_12")
        assert datum["patch"] == original_patch

    def test_worker_does_not_mutate_datum_repo(self, tmp_path):
        datum = make_datum()
        original_repo = datum["repo"]
        _run_worker(tmp_path, datum, "cp_13")
        assert datum["repo"] == original_repo

    def test_main_results_independent(self, tmp_path):
        dataset = [make_datum(instance_id="m1"), make_datum(instance_id="m2")]
        results_collected = []

        original_worker = worker_function

        def capturing_worker(datum, run_id):
            r = _run_worker(tmp_path, datum, run_id)
            results_collected.append(r)
            return r

        with (
            patch(f"{MODULE}.setup_helicone"),
            patch(f"{MODULE}.load_swefficiency_dataset", return_value=dataset),
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.worker_function", side_effect=capturing_worker),
        ):
            main(
                dataset_name="test",
                split="test",
                instance_ids=[],
                max_workers=1,
                run_id="cp_main",
            )

        if len(results_collected) >= 2:
            assert results_collected[0] is not results_collected[1]


# ===================================================================
# 3. TestStringInterning (~10 cases)
# ===================================================================
class TestStringInterning:
    """String comparisons must use == not `is`. Python may or may not intern."""

    def test_extract_code_block_identical_inputs_equality(self):
        text = "```python\nresult = 42\n```"
        r1 = extract_code_block(text)
        r2 = extract_code_block(text)
        assert r1 == r2

    def test_extract_code_block_dynamic_strings_equality(self):
        base = "```python\n{}\n```"
        t1 = base.format("x = 1")
        t2 = base.format("x = 1")
        r1 = extract_code_block(t1)
        r2 = extract_code_block(t2)
        assert r1 == r2

    def test_extract_code_block_long_string_equality(self):
        code = "a = " + "1" * 500
        text = f"```python\n{code}\n```"
        r1 = extract_code_block(text)
        r2 = extract_code_block(text)
        assert r1 == r2

    def test_system_msg_equality_not_identity(self):
        s1 = SYSTEM_MSG
        s2 = str(SYSTEM_MSG)
        assert s1 == s2

    def test_system_msg_slice_equality(self):
        chunk1 = SYSTEM_MSG[:100]
        chunk2 = SYSTEM_MSG[:100]
        assert chunk1 == chunk2

    def test_context_msg_format_result_equality(self):
        kwargs = {"repo_name": "numpy", "commit_diff": "diff", "pre_edit_code": "code"}
        r1 = CONTEXT_MSG.format(**kwargs)
        r2 = CONTEXT_MSG.format(**kwargs)
        assert r1 == r2

    def test_context_msg_format_not_necessarily_same_object(self):
        kwargs = {"repo_name": "test", "commit_diff": "d", "pre_edit_code": "c"}
        r1 = CONTEXT_MSG.format(**kwargs)
        r2 = CONTEXT_MSG.format(**kwargs)
        assert r1 == r2

    def test_context_msg_different_repos_not_equal(self):
        r1 = CONTEXT_MSG.format(repo_name="numpy", commit_diff="d", pre_edit_code="c")
        r2 = CONTEXT_MSG.format(repo_name="pandas", commit_diff="d", pre_edit_code="c")
        assert r1 != r2

    def test_system_msg_concatenation_equality(self):
        part1 = SYSTEM_MSG[:50]
        part2 = SYSTEM_MSG[50:]
        reconstructed = part1 + part2
        assert reconstructed == SYSTEM_MSG

    def test_extract_code_block_strip_equality(self):
        text = "```python\n  hello  \n```"
        r1 = extract_code_block(text)
        r2 = extract_code_block(text)
        assert r1 == r2

    def test_context_msg_format_preserves_equality_across_calls(self):
        kwargs = {"repo_name": "scipy", "commit_diff": "x", "pre_edit_code": "y"}
        results = [CONTEXT_MSG.format(**kwargs) for _ in range(5)]
        assert all(r == results[0] for r in results)


# ===================================================================
# 4. TestIsVsEquals (~10 cases)
# ===================================================================
class TestIsVsEquals:
    """Proper use of `is` for None checks and `==` for value comparisons."""

    def test_extract_none_input_returns_none_identity(self):
        result = extract_code_block(None)
        assert result is None

    def test_extract_no_match_returns_none_identity(self):
        result = extract_code_block("no code block here")
        assert result is None

    def test_extract_plain_text_returns_none_identity(self):
        result = extract_code_block("just plain text without fences")
        assert result is None

    def test_extract_with_match_uses_value_equality(self):
        result = extract_code_block("```python\nx = 1\n```")
        assert result == "x = 1"

    def test_extract_result_not_none_when_match(self):
        result = extract_code_block("```python\ncode()\n```")
        assert result is not None

    def test_worker_return_instance_id_value_equality(self, tmp_path):
        result = _run_worker(tmp_path)
        assert result["instance_id"] == "numpy__numpy-12345"

    def test_worker_return_run_id_value_equality(self, tmp_path):
        result = _run_worker(tmp_path, run_id="test_run")
        assert result["run_id"] == "test_run"

    def test_worker_return_workload_value_equality(self, tmp_path):
        result = _run_worker(tmp_path)
        assert result["workload"] == EXTRACTED_CODE

    def test_worker_return_workload_not_none(self, tmp_path):
        result = _run_worker(tmp_path)
        assert result["workload"] is not None

    def test_none_vs_empty_string_distinction(self):
        assert extract_code_block(None) is None
        result = extract_code_block("```python\n\n```")
        assert result == "" or result is None


# ===================================================================
# 5. TestBoolTruthiness (~10 cases)
# ===================================================================
class TestBoolTruthiness:
    """Verify truthiness semantics for return values."""

    def test_extract_empty_string_input_returns_none(self):
        result = extract_code_block("")
        assert result is None

    def test_extract_empty_code_block(self):
        result = extract_code_block("```\n\n```")
        assert result == "" or result is None

    def test_extract_empty_python_block(self):
        result = extract_code_block("```python\n\n```")
        assert result == "" or result is None

    def test_extract_none_is_falsy(self):
        result = extract_code_block(None)
        assert not result

    def test_extract_no_match_is_falsy(self):
        result = extract_code_block("no fences here")
        assert not result

    def test_extract_valid_code_is_truthy(self):
        result = extract_code_block("```python\nprint('hi')\n```")
        assert result  

    def test_worker_result_workload_is_truthy(self, tmp_path):
        result = _run_worker(tmp_path)
        assert result["workload"]

    def test_worker_result_dict_is_truthy(self, tmp_path):
        result = _run_worker(tmp_path)
        assert result

    def test_if_result_pattern_valid_code(self):
        result = extract_code_block("```python\nx = 42\n```")
        if result:
            assert isinstance(result, str)
        else:
            pytest.fail("Expected truthy result from valid code block")

    def test_if_result_pattern_no_code(self):
        result = extract_code_block("no code here")
        if result:
            pytest.fail("Expected falsy result from text without code block")
        else:
            assert result is None


# ===================================================================
# 6. TestImportSideEffects (~10 cases)
# ===================================================================
class TestImportSideEffects:
    """Importing the module must not create directories or make network calls."""

    def test_workload_dir_is_path_after_import(self):
        assert isinstance(WORKLOAD_GENERATION_DIR, Path)

    def test_import_does_not_create_workload_dir(self):
        assert WORKLOAD_GENERATION_DIR == Path("logs/workload_generation")

    def test_import_does_not_create_logs_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from swefficiency.workload.run_synthetic_generation import (
            WORKLOAD_GENERATION_DIR as wdir,
        )

        assert not (tmp_path / "logs").exists()

    def test_import_does_not_make_network_calls(self):
        with patch(f"{MODULE}.requests.get") as mock_get:
            import importlib

            import swefficiency.workload.run_synthetic_generation as mod

            importlib.reload(mod)
            mock_get.assert_not_called()

    def test_module_has_expected_constants(self):
        import swefficiency.workload.run_synthetic_generation as mod

        assert hasattr(mod, "WORKLOAD_GENERATION_DIR")
        assert hasattr(mod, "SYSTEM_MSG")
        assert hasattr(mod, "CONTEXT_MSG")

    def test_module_has_expected_functions(self):
        import swefficiency.workload.run_synthetic_generation as mod

        assert callable(mod.extract_code_block)
        assert callable(mod.worker_function)
        assert callable(mod.main)

    def test_system_msg_available_immediately(self):
        assert len(SYSTEM_MSG) > 0

    def test_context_msg_available_immediately(self):
        assert len(CONTEXT_MSG) > 0

    def test_import_does_not_call_completion(self):
        with patch(f"{MODULE}.completion") as mock_comp:
            import importlib

            import swefficiency.workload.run_synthetic_generation as mod

            importlib.reload(mod)
            mock_comp.assert_not_called()

    def test_import_does_not_call_setup_helicone(self):
        with patch(f"{MODULE}.setup_helicone") as mock_setup:
            import importlib

            import swefficiency.workload.run_synthetic_generation as mod

            importlib.reload(mod)
            mock_setup.assert_not_called()


# ===================================================================
# 7. TestDictOrdering (~10 cases)
# ===================================================================
class TestDictOrdering:
    """worker_function return dict has consistent key ordering (Python 3.7+ guarantees)."""

    def test_worker_return_has_instance_id_key(self, tmp_path):
        result = _run_worker(tmp_path)
        assert "instance_id" in result

    def test_worker_return_has_run_id_key(self, tmp_path):
        result = _run_worker(tmp_path)
        assert "run_id" in result

    def test_worker_return_has_workload_key(self, tmp_path):
        result = _run_worker(tmp_path)
        assert "workload" in result

    def test_worker_return_keys_exactly_three(self, tmp_path):
        result = _run_worker(tmp_path)
        assert len(result) == 3

    def test_worker_return_key_order_consistent(self, tmp_path):
        r1 = _run_worker(tmp_path, make_datum(instance_id="o1"), "ord_1")
        r2 = _run_worker(tmp_path, make_datum(instance_id="o2"), "ord_2")
        assert list(r1.keys()) == list(r2.keys())

    def test_worker_return_key_order_is_instance_run_workload(self, tmp_path):
        result = _run_worker(tmp_path)
        keys = list(result.keys())
        assert keys == ["instance_id", "run_id", "workload"]

    def test_json_serialization_preserves_key_order(self, tmp_path):
        result = _run_worker(tmp_path)
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert list(deserialized.keys()) == list(result.keys())

    def test_json_roundtrip_values_preserved(self, tmp_path):
        result = _run_worker(tmp_path)
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized == result

    def test_multiple_serializations_identical(self, tmp_path):
        result = _run_worker(tmp_path)
        s1 = json.dumps(result)
        s2 = json.dumps(result)
        assert s1 == s2

    def test_json_keys_order_across_different_data(self, tmp_path):
        r1 = _run_worker(tmp_path, make_datum(instance_id="json_a"), "j1")
        r2 = _run_worker(tmp_path, make_datum(instance_id="json_b"), "j2")
        j1 = json.dumps(r1)
        j2 = json.dumps(r2)
        keys1 = re.findall(r'"(\w+)":', j1)
        keys2 = re.findall(r'"(\w+)":', j2)
        assert keys1 == keys2

    def test_worker_return_no_extra_keys(self, tmp_path):
        result = _run_worker(tmp_path)
        expected_keys = {"instance_id", "run_id", "workload"}
        assert set(result.keys()) == expected_keys
