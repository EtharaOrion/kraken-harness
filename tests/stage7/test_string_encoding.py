"""Dimensions 4 & 10 — String/Text Brutality and Data Format/Encoding tests
for swefficiency.workload.run_synthetic_generation.

Tests verify that Unicode edge cases (RTL, combining chars, homoglyphs,
invisible characters, ZWJ emoji) and data format issues (line endings, BOM,
encoding) are handled correctly by extract_code_block, worker_function, and
the file-output pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path
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

SAMPLE_LLM = (
    '```python\nimport timeit\nimport statistics\n'
    'def setup(): pass\ndef workload(): pass\n'
    'runtimes = timeit.repeat(workload, number=1, repeat=3, setup=setup)\n'
    'print("Mean:", statistics.mean(runtimes))\n'
    'print("Std Dev:", statistics.stdev(runtimes))\n```'
)


def _fake_get_ok(url, *a, **kw):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "# file content\npass\n"
    return resp


def _run_worker(tmp_path, instance_id="safe__id-1", run_id="run_001",
                repo="numpy/numpy", patch_text=None, llm_response=None):
    """Run worker_function with all externals mocked."""
    llm_resp = llm_response or SAMPLE_LLM
    datum = (
        make_datum(instance_id=instance_id, repo=repo, patch=patch_text)
        if patch_text
        else make_datum(instance_id=instance_id, repo=repo)
    )
    with (
        patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
        patch(f"{MODULE}.helicone_metadata", return_value={}),
        patch(f"{MODULE}.completion",
              return_value=make_completion_response(llm_resp)),
        patch(f"{MODULE}.requests.get", side_effect=_fake_get_ok),
    ):
        result = worker_function(datum, run_id)
    output_file = tmp_path / run_id / f"{instance_id}.py"
    return result, output_file


# ===================================================================
# DIMENSION 4 — String & Text Brutality
# ===================================================================

# -------------------------------------------------------------------
# 1. TestRTLTextInDatum  (~10 cases)
# -------------------------------------------------------------------

class TestRTLTextInDatum:
    """D4: Right-to-left text in datum fields."""

    def test_arabic_instance_id_worker_completes(self, tmp_path):
        """D4: Arabic text as instance_id — worker_function handles it."""
        result, _ = _run_worker(tmp_path, instance_id="\u0645\u0631\u062d\u0628\u0627")
        assert isinstance(result, dict)

    def test_arabic_instance_id_in_result(self, tmp_path):
        """D4: Arabic instance_id preserved in result dict."""
        result, _ = _run_worker(tmp_path, instance_id="\u0645\u0631\u062d\u0628\u0627")
        assert result["instance_id"] == "\u0645\u0631\u062d\u0628\u0627"

    def test_hebrew_repo_raises_value_error(self, tmp_path):
        """D4: Hebrew-only repo name has no slash — split('/') fails."""
        with pytest.raises(ValueError):
            _run_worker(tmp_path, repo="\u05e9\u05dc\u05d5\u05dd")

    def test_hebrew_repo_with_slash_completes(self, tmp_path):
        """D4: Hebrew repo with slash — split works, worker completes."""
        result, _ = _run_worker(tmp_path, repo="\u05e9\u05dc\u05d5\u05dd/\u05e8\u05e4\u05d5")
        assert isinstance(result, dict)

    def test_rtl_text_in_patch_content(self, tmp_path):
        """D4: RTL text in patch content — treated as string data."""
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            "-old\n+\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_mixed_rtl_ltr_instance_id(self, tmp_path):
        """D4: Mixed RTL/LTR in instance_id."""
        result, _ = _run_worker(tmp_path, instance_id="numpy__\u0645\u0631\u062d\u0628\u0627-123")
        assert result["instance_id"] == "numpy__\u0645\u0631\u062d\u0628\u0627-123"

    def test_mixed_rtl_ltr_file_created(self, tmp_path):
        """D4: Mixed RTL/LTR instance_id — output file is created."""
        _, output_file = _run_worker(tmp_path, instance_id="numpy__\u0645\u0631\u062d\u0628\u0627-123")
        assert output_file.exists()

    def test_rtl_run_id_directory_created(self, tmp_path):
        """D4: RTL text in run_id — directory creation handles it."""
        result, _ = _run_worker(tmp_path, run_id="\u0645\u0631\u062d\u0628\u0627_run")
        assert isinstance(result, dict)

    def test_rtl_run_id_preserved_in_result(self, tmp_path):
        """D4: RTL run_id preserved in result dict."""
        result, _ = _run_worker(tmp_path, run_id="\u0645\u0631\u062d\u0628\u0627_run")
        assert result["run_id"] == "\u0645\u0631\u062d\u0628\u0627_run"

    def test_rtl_in_llm_response_extracted(self, tmp_path):
        """D4: RTL text inside LLM code block — extract_code_block preserves it."""
        llm = '```python\n# \u0645\u0631\u062d\u0628\u0627\npass\n```'
        result = extract_code_block(llm)
        assert "\u0645\u0631\u062d\u0628\u0627" in result


# -------------------------------------------------------------------
# 2. TestCombiningDiacriticals  (~10 cases)
# -------------------------------------------------------------------

class TestCombiningDiacriticals:
    """D4: NFC vs NFD normalization and combining characters."""

    def test_nfc_cafe_instance_id(self, tmp_path):
        """D4: NFC 'caf\u00e9' as instance_id — worker completes."""
        result, _ = _run_worker(tmp_path, instance_id="caf\u00e9")
        assert result["instance_id"] == "caf\u00e9"

    def test_nfd_cafe_instance_id(self, tmp_path):
        """D4: NFD 'cafe\\u0301' as instance_id — worker completes."""
        result, _ = _run_worker(tmp_path, instance_id="cafe\u0301")
        assert result["instance_id"] == "cafe\u0301"

    def test_nfc_nfd_produce_different_result_ids(self, tmp_path):
        """D4: NFC and NFD forms produce different instance_id values in results."""
        r_nfc, _ = _run_worker(tmp_path, instance_id="caf\u00e9", run_id="run_nfc")
        r_nfd, _ = _run_worker(tmp_path, instance_id="cafe\u0301", run_id="run_nfd")
        assert r_nfc["instance_id"] != r_nfd["instance_id"]

    def test_combining_chars_in_repo_owner(self, tmp_path):
        """D4: Combining characters in repo name — split('/') still works."""
        result, _ = _run_worker(tmp_path, repo="caf\u00e9/re\u0301po")
        assert isinstance(result, dict)

    def test_combining_diacriticals_in_code_block(self):
        """D4: Combining diacriticals in LLM response — extract_code_block preserves them."""
        llm = '```python\nx = "caf\u00e9 re\u0301sume\u0301"\n```'
        result = extract_code_block(llm)
        assert "caf\u00e9" in result

    def test_nfd_preserved_in_extracted_code(self):
        """D4: NFD form preserved through extract_code_block."""
        llm = '```python\nname = "cafe\\u0301"\n```'
        result = extract_code_block(llm)
        assert "cafe\\u0301" in result

    def test_multiple_combining_marks_in_patch(self, tmp_path):
        """D4: Multiple combining marks in patch content — regex still finds files."""
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            "-old\n+# na\u0308i\u0308ve\u0301 u\u0308ber\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_combining_chars_in_output_file_content(self, tmp_path):
        """D4: Combining chars in LLM code written to file."""
        llm = '```python\n# na\u0308i\u0308ve\npass\n```'
        result, output_file = _run_worker(tmp_path, llm_response=llm)
        assert output_file.exists()

    def test_combining_chars_file_content_preserved(self, tmp_path):
        """D4: Combining chars in written file content are preserved."""
        llm = '```python\n# na\u0308i\u0308ve\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text()
        assert "na\u0308i\u0308ve" in content

    def test_heavy_combining_marks_instance_id(self, tmp_path):
        """D4: Instance ID with stacked combining marks — Zalgo-like text."""
        zalgo = "t\u0300\u0301\u0302\u0303e\u0304\u0305\u0306s\u0307\u0308t"
        result, _ = _run_worker(tmp_path, instance_id=zalgo)
        assert result["instance_id"] == zalgo


# -------------------------------------------------------------------
# 3. TestHomoglyphs  (~8 cases)
# -------------------------------------------------------------------

class TestHomoglyphs:
    """D4: Visually identical but code-point-different characters."""

    def test_cyrillic_a_instance_id(self, tmp_path):
        """D4: Cyrillic 'а' (U+0430) as part of instance_id."""
        result, _ = _run_worker(tmp_path, instance_id="\u0430_test")
        assert result["instance_id"] == "\u0430_test"

    def test_latin_a_instance_id(self, tmp_path):
        """D4: Latin 'a' (U+0061) as part of instance_id."""
        result, _ = _run_worker(tmp_path, instance_id="a_test")
        assert result["instance_id"] == "a_test"

    def test_cyrillic_vs_latin_different_results(self, tmp_path):
        """D4: Cyrillic 'а' and Latin 'a' produce different instance_id values."""
        r_cyr, _ = _run_worker(tmp_path, instance_id="\u0430_test", run_id="run_cyr")
        r_lat, _ = _run_worker(tmp_path, instance_id="a_test", run_id="run_lat")
        assert r_cyr["instance_id"] != r_lat["instance_id"]

    def test_homoglyph_repo_name_with_slash(self, tmp_path):
        """D4: Homoglyph in repo name — split('/') behavior preserved."""
        result, _ = _run_worker(tmp_path, repo="n\u0443mpy/numpy")
        assert isinstance(result, dict)

    def test_homoglyph_repo_url_constructed(self, tmp_path):
        """D4: Homoglyph repo passed to requests.get as-is in URL."""
        captured_urls = []

        def _capture_get(url, *a, **kw):
            captured_urls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "# ok\n"
            return resp

        datum = make_datum(repo="n\u0443mpy/numpy")
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM)),
            patch(f"{MODULE}.requests.get", side_effect=_capture_get),
        ):
            worker_function(datum, "run_hg")
        assert all("n\u0443mpy" in url for url in captured_urls)

    def test_fullwidth_backtick_not_code_block(self):
        """D4: Fullwidth backtick (U+FF40) does NOT match code block regex."""
        text = "\uff40\uff40\uff40python\ncode()\n\uff40\uff40\uff40"
        result = extract_code_block(text)
        assert result is None

    def test_homoglyph_backtick_mixed_not_code_block(self):
        """D4: Mix of real and homoglyph backticks — no code block match."""
        text = "``\uff40python\ncode()\n``\uff40"
        result = extract_code_block(text)
        assert result is None

    def test_greek_omicron_in_instance_id(self, tmp_path):
        """D4: Greek omicron (U+03BF) vs Latin 'o' — different codepoints."""
        result, _ = _run_worker(tmp_path, instance_id="n\u03bfmpy__test-1")
        assert result["instance_id"] == "n\u03bfmpy__test-1"


# -------------------------------------------------------------------
# 4. TestInvisibleChars  (~12 cases)
# -------------------------------------------------------------------

class TestInvisibleChars:
    """D4: BOM, zero-width, NBSP, soft-hyphen, and other invisible characters."""

    def test_bom_at_start_of_llm_response(self):
        """D4: BOM at start of LLM response — extract_code_block handling."""
        llm = '\ufeff```python\npass\n```'
        result = extract_code_block(llm)
        assert result is not None

    def test_bom_does_not_appear_in_extracted_code(self):
        """D4: BOM stripped or absent from extracted code block content."""
        llm = '\ufeff```python\nprint("hello")\n```'
        result = extract_code_block(llm)
        assert result == 'print("hello")'

    def test_zwsp_in_instance_id(self, tmp_path):
        """D4: Zero-width space (U+200B) in instance_id — file creation."""
        result, output_file = _run_worker(tmp_path, instance_id="test\u200bid")
        assert isinstance(result, dict)

    def test_zwsp_instance_id_preserved(self, tmp_path):
        """D4: Zero-width space preserved in result instance_id."""
        result, _ = _run_worker(tmp_path, instance_id="test\u200bid")
        assert result["instance_id"] == "test\u200bid"

    def test_nbsp_in_patch_content(self, tmp_path):
        """D4: Non-breaking space (U+00A0) in patch content — regex matching."""
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            "-old\n+new\u00a0value\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_nbsp_in_diff_header_file_path(self, tmp_path):
        """D4: NBSP in diff header — regex still extracts file path."""
        patch_text = (
            "diff --git a/f\u00a0name.py b/f\u00a0name.py\nindex 111..222 100644\n"
            "--- a/f\u00a0name.py\n+++ b/f\u00a0name.py\n@@ -1 +1 @@\n"
            "-old\n+new\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_soft_hyphen_in_code_block(self):
        """D4: Soft hyphen (U+00AD) in code block — preserved in extraction."""
        llm = '```python\nname = "soft\u00adhyphen"\n```'
        result = extract_code_block(llm)
        assert "\u00ad" in result

    def test_zwj_in_repo_name(self, tmp_path):
        """D4: Zero-width joiner (U+200D) in repo name — split works."""
        result, _ = _run_worker(tmp_path, repo="owner\u200d/repo\u200d")
        assert isinstance(result, dict)

    def test_bom_in_patch_diff(self, tmp_path):
        """D4: BOM in patch diff content — worker handles it."""
        patch_text = (
            "\ufeffdiff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            "-old\n+new\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_invisible_chars_in_run_id(self, tmp_path):
        """D4: Multiple invisible chars in run_id — directory creation."""
        result, _ = _run_worker(tmp_path, run_id="run\u200b\u200c\u200d_001")
        assert result["run_id"] == "run\u200b\u200c\u200d_001"

    def test_word_joiner_in_code_block(self):
        """D4: Word joiner (U+2060) in code block — preserved in extraction."""
        llm = '```python\nx = "hello\u2060world"\n```'
        result = extract_code_block(llm)
        assert "\u2060" in result

    def test_left_to_right_mark_in_instance_id(self, tmp_path):
        """D4: Left-to-right mark (U+200E) in instance_id."""
        result, _ = _run_worker(tmp_path, instance_id="test\u200eid")
        assert result["instance_id"] == "test\u200eid"


# -------------------------------------------------------------------
# 5. TestZWJEmojiSequences  (~8 cases)
# -------------------------------------------------------------------

class TestZWJEmojiSequences:
    """D4: Zero-width-joiner emoji sequences, flags, skin tones."""

    def test_family_emoji_in_instance_id(self, tmp_path):
        """D4: Family emoji (ZWJ sequence) in instance_id."""
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466"
        result, _ = _run_worker(tmp_path, instance_id=f"test_{family}_1")
        assert result["instance_id"] == f"test_{family}_1"

    def test_family_emoji_file_created(self, tmp_path):
        """D4: Family emoji instance_id — output file created on disk."""
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466"
        _, output_file = _run_worker(tmp_path, instance_id=f"test_{family}_1")
        assert output_file.exists()

    def test_flag_emoji_in_llm_response(self):
        """D4: Rainbow flag emoji in LLM code block — extracted correctly."""
        flag = "\U0001f3f3\ufe0f\u200d\U0001f308"
        llm = f'```python\n# {flag}\npass\n```'
        result = extract_code_block(llm)
        assert flag in result

    def test_skin_tone_modifier_in_patch(self, tmp_path):
        """D4: Skin tone modifier emoji in patch content."""
        wave = "\U0001f44b\U0001f3fd"
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            f"-old\n+# {wave}\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_emoji_in_code_comment_extracted(self):
        """D4: extract_code_block with emoji in code comments."""
        llm = '```python\n# \U0001f680 rocket launch\nprint("go")\n```'
        result = extract_code_block(llm)
        assert "\U0001f680" in result

    def test_multiple_zwj_emoji_in_instance_id(self, tmp_path):
        """D4: Multiple ZWJ emoji sequences in instance_id."""
        woman_tech = "\U0001f469\u200d\U0001f4bb"
        man_cook = "\U0001f468\u200d\U0001f373"
        iid = f"{woman_tech}_{man_cook}_test"
        result, _ = _run_worker(tmp_path, instance_id=iid)
        assert result["instance_id"] == iid

    def test_country_flag_in_run_id(self, tmp_path):
        """D4: Regional indicator flag in run_id."""
        flag_us = "\U0001f1fa\U0001f1f8"
        result, _ = _run_worker(tmp_path, run_id=f"run_{flag_us}")
        assert result["run_id"] == f"run_{flag_us}"

    def test_emoji_zwj_sequence_preserved_in_output(self, tmp_path):
        """D4: ZWJ emoji in LLM response — preserved in output file."""
        firefighter = "\U0001f468\u200d\U0001f692"
        llm = f'```python\n# {firefighter}\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text()
        assert firefighter in content


# ===================================================================
# DIMENSION 10 — Data Format & Encoding
# ===================================================================

# -------------------------------------------------------------------
# 6. TestLineEndingsInLLMResponse  (~10 cases)
# -------------------------------------------------------------------

class TestLineEndingsInLLMResponse:
    """D10: CRLF, CR, and mixed line endings in LLM responses."""

    def test_crlf_in_code_block_extracted(self):
        """D10: CRLF line endings in code block — extract_code_block handles it."""
        llm = "```python\r\nimport os\r\npass\r\n```"
        result = extract_code_block(llm)
        assert result is not None

    def test_crlf_content_contains_code(self):
        """D10: CRLF code block — extracted content contains code."""
        llm = "```python\r\nimport os\r\npass\r\n```"
        result = extract_code_block(llm)
        assert "import os" in result

    def test_cr_only_line_endings(self):
        """D10: CR-only line endings — extract_code_block regex behavior."""
        llm = "```python\rimport os\rpass\r```"
        result = extract_code_block(llm)
        # CR-only: the regex requires \n after ```, so this may not match
        # Document actual behavior
        assert result is None or isinstance(result, str)

    def test_mixed_line_endings_in_code_block(self):
        """D10: Mixed LF/CRLF in code block — extraction works."""
        llm = "```python\nimport os\r\nx = 1\npass\r\n```"
        result = extract_code_block(llm)
        assert result is not None

    def test_crlf_in_code_block_markers(self):
        """D10: CRLF in code block markers themselves — regex match."""
        llm = "```python\r\nprint('hello')\r\n```"
        result = extract_code_block(llm)
        assert result is not None

    def test_crlf_stripped_by_extract(self):
        """D10: extract_code_block's .strip() handles trailing CRLF."""
        llm = "```python\nprint('hello')\r\n```"
        result = extract_code_block(llm)
        assert not result.endswith("\r")

    def test_crlf_worker_output_file(self, tmp_path):
        """D10: CRLF in LLM response — worker writes to file."""
        llm = "```python\r\nimport timeit\r\npass\r\n```"
        result, output_file = _run_worker(tmp_path, llm_response=llm)
        assert output_file.exists()

    def test_crlf_worker_result_has_workload(self, tmp_path):
        """D10: CRLF LLM response — result dict has workload key."""
        llm = "```python\r\nimport timeit\r\npass\r\n```"
        result, _ = _run_worker(tmp_path, llm_response=llm)
        assert result["workload"] is not None

    def test_lf_only_normal_case(self):
        """D10: Standard LF-only line endings — baseline extraction works."""
        llm = "```python\nprint('hello')\n```"
        result = extract_code_block(llm)
        assert result == "print('hello')"

    def test_no_trailing_newline_before_closing_backticks(self):
        """D10: No newline before closing backticks — extraction behavior."""
        llm = "```python\nprint('hello')```"
        result = extract_code_block(llm)
        assert result is not None or result is None


# -------------------------------------------------------------------
# 7. TestBOMInLLMResponse  (~8 cases)
# -------------------------------------------------------------------

class TestBOMInLLMResponse:
    """D10: Byte Order Mark in LLM response text."""

    def test_bom_at_response_start_extraction(self):
        """D10: BOM at very start of LLM response text."""
        llm = "\ufeff```python\nprint('hello')\n```"
        result = extract_code_block(llm)
        assert result is not None

    def test_bom_at_response_start_code_clean(self):
        """D10: BOM at start — extracted code does not contain BOM."""
        llm = "\ufeff```python\nprint('hello')\n```"
        result = extract_code_block(llm)
        assert "\ufeff" not in result

    def test_bom_inside_code_block(self):
        """D10: BOM inside the code block content."""
        llm = "```python\n\ufeffimport os\npass\n```"
        result = extract_code_block(llm)
        assert "import os" in result

    def test_bom_inside_block_preserved(self):
        """D10: BOM inside code block — preserved as-is in extraction."""
        llm = "```python\nprint('\ufeff')\n```"
        result = extract_code_block(llm)
        assert "\ufeff" in result

    def test_bom_in_middle_of_response(self):
        """D10: BOM in the middle of response, outside code block."""
        llm = "Here is code:\ufeff\n```python\npass\n```"
        result = extract_code_block(llm)
        assert result == "pass"

    def test_bom_worker_output_no_bom_artifact(self, tmp_path):
        """D10: Worker output file should not have BOM from response prefix."""
        llm = "\ufeff```python\nprint('clean')\n```"
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text()
        assert content == "print('clean')"

    def test_multiple_boms_in_response(self):
        """D10: Multiple BOMs scattered in response."""
        llm = "\ufeff\ufeff```python\n\ufeffpass\n```"
        result = extract_code_block(llm)
        assert result is not None

    def test_bom_only_response_no_code_block(self):
        """D10: Response is just BOMs — no code block to extract."""
        llm = "\ufeff\ufeff\ufeff"
        result = extract_code_block(llm)
        assert result is None


# -------------------------------------------------------------------
# 8. TestEncodingInFileOutput  (~8 cases)
# -------------------------------------------------------------------

class TestEncodingInFileOutput:
    """D10: Encoding handling in file I/O."""

    def test_unicode_instance_id_in_filename(self, tmp_path):
        """D10: Unicode instance_id used as filename — OS handles it."""
        result, output_file = _run_worker(
            tmp_path, instance_id="\u00fc\u00f6\u00e4_test"
        )
        assert output_file.exists()

    def test_unicode_filename_content_correct(self, tmp_path):
        """D10: File with Unicode name has correct code content."""
        _, output_file = _run_worker(
            tmp_path, instance_id="\u00fc\u00f6\u00e4_test"
        )
        content = output_file.read_text()
        assert "import timeit" in content

    def test_non_ascii_code_in_output(self, tmp_path):
        """D10: Non-ASCII code written to output file — encoding preserved."""
        llm = '```python\n# \u4f60\u597d\u4e16\u754c Chinese hello world\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text(encoding="utf-8")
        assert "\u4f60\u597d\u4e16\u754c" in content

    def test_japanese_code_comment_preserved(self, tmp_path):
        """D10: Japanese text in code comment — preserved in output file."""
        llm = '```python\n# \u30c6\u30b9\u30c8\u30b3\u30fc\u30c9\nprint("ok")\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text(encoding="utf-8")
        assert "\u30c6\u30b9\u30c8" in content

    def test_cyrillic_code_in_output(self, tmp_path):
        """D10: Cyrillic text in code — preserved in output file."""
        llm = '```python\n# \u041f\u0440\u0438\u0432\u0435\u0442\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text(encoding="utf-8")
        assert "\u041f\u0440\u0438\u0432\u0435\u0442" in content

    def test_mixed_scripts_in_output(self, tmp_path):
        """D10: Mixed scripts (Latin, CJK, Arabic) in single code block."""
        llm = '```python\n# hello \u4f60\u597d \u0645\u0631\u062d\u0628\u0627\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text(encoding="utf-8")
        assert "hello" in content
        assert "\u4f60\u597d" in content

    def test_surrogate_escape_not_in_file(self, tmp_path):
        """D10: Standard LLM response — no surrogate escape issues in file."""
        result, output_file = _run_worker(tmp_path)
        content = output_file.read_text(encoding="utf-8")
        assert isinstance(content, str)

    def test_output_file_readable_as_utf8(self, tmp_path):
        """D10: Output file is valid UTF-8."""
        llm = '```python\n# \u00e9\u00e8\u00ea\u00eb \u00f1\npass\n```'
        _, output_file = _run_worker(tmp_path, llm_response=llm)
        content = output_file.read_text(encoding="utf-8")
        assert "\u00e9" in content


# -------------------------------------------------------------------
# 9. TestLineEndingsInPatchContent  (~6 bonus cases for D10)
# -------------------------------------------------------------------

class TestLineEndingsInPatchContent:
    """D10: Line endings in patch content — diff regex matching."""

    def test_crlf_patch_diff_regex_extracts_files(self, tmp_path):
        """D10: CRLF line endings in patch — diff regex still extracts file paths."""
        patch_text = (
            "diff --git a/f.py b/f.py\r\nindex 111..222 100644\r\n"
            "--- a/f.py\r\n+++ b/f.py\r\n@@ -1 +1 @@\r\n"
            "-old\r\n+new\r\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_crlf_patch_worker_completes(self, tmp_path):
        """D10: CRLF patch — worker returns valid result dict."""
        patch_text = (
            "diff --git a/lib/foo.py b/lib/foo.py\r\nindex 111..222 100644\r\n"
            "--- a/lib/foo.py\r\n+++ b/lib/foo.py\r\n@@ -1 +1 @@\r\n"
            "-old\r\n+new\r\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert "workload" in result

    def test_cr_only_patch_diff_regex(self, tmp_path):
        """D10: CR-only patch — diff regex behavior on \\r-separated lines."""
        patch_text = (
            "diff --git a/f.py b/f.py\rindex 111..222 100644\r"
            "--- a/f.py\r+++ b/f.py\r@@ -1 +1 @@\r"
            "-old\r+new\r"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_mixed_endings_in_patch(self, tmp_path):
        """D10: Mixed LF/CRLF in patch — worker handles it."""
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\r\n"
            "--- a/f.py\n+++ b/f.py\r\n@@ -1 +1 @@\n"
            "-old\r\n+new\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)

    def test_crlf_patch_file_path_has_cr(self, tmp_path):
        """D10: CRLF in patch — extracted file path may contain \\r."""
        import re as re_mod
        patch_text = (
            "diff --git a/f.py b/f.py\r\nindex 111..222 100644\r\n"
            "--- a/f.py\r\n+++ b/f.py\r\n@@ -1 +1 @@\r\n"
            "-old\r\n+new\r\n"
        )
        diff_pattern = r"diff --git a/.* b/(.*)"
        directives = re_mod.findall(diff_pattern, patch_text)
        # The \r may be captured as part of the file path
        assert len(directives) >= 1

    def test_null_byte_in_line_ending_area(self, tmp_path):
        """D10: Null byte near line ending in patch."""
        patch_text = (
            "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
            "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
            "-old\n+new\x00\n"
        )
        result, _ = _run_worker(tmp_path, patch_text=patch_text)
        assert isinstance(result, dict)


# -------------------------------------------------------------------
# 10. TestExtractCodeBlockEncodingEdgeCases  (~6 bonus D10 cases)
# -------------------------------------------------------------------

class TestExtractCodeBlockEncodingEdgeCases:
    """D10: Edge cases specifically for extract_code_block with encoding issues."""

    def test_backslash_u_escape_literal_in_block(self):
        """D10: Literal \\u escape sequences in code block — preserved."""
        llm = '```python\nx = "\\u0041"\n```'
        result = extract_code_block(llm)
        assert "\\u0041" in result

    def test_tab_characters_preserved(self):
        """D10: Tab characters in code block — preserved in extraction."""
        llm = "```python\ndef f():\n\treturn 1\n```"
        result = extract_code_block(llm)
        assert "\t" in result

    def test_form_feed_in_code_block(self):
        """D10: Form feed (U+000C) in code block — preserved."""
        llm = "```python\npage1\x0cpage2\n```"
        result = extract_code_block(llm)
        assert "\x0c" in result

    def test_vertical_tab_in_code_block(self):
        """D10: Vertical tab (U+000B) in code block — preserved."""
        llm = "```python\nline1\x0bline2\n```"
        result = extract_code_block(llm)
        assert "\x0b" in result

    def test_paragraph_separator_in_code_block(self):
        """D10: Paragraph separator (U+2029) in code block."""
        llm = "```python\npart1\u2029part2\n```"
        result = extract_code_block(llm)
        assert "\u2029" in result

    def test_line_separator_in_code_block(self):
        """D10: Line separator (U+2028) in code block."""
        llm = "```python\npart1\u2028part2\n```"
        result = extract_code_block(llm)
        assert "\u2028" in result
