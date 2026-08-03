"""OSS-Instruct helpers — sampler, parser, decontamination."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from repo2rlenv.pipelines._oss_instruct import (
    DEFAULT_BENCHMARK_PHRASES,
    _looks_substantive,
    extract_task_module_imports,
    has_benchmark_overlap,
    is_excluded,
    list_source_files,
    parse_task_response,
    references_task_module,
    sample_seed,
    solution_leaks_into_problem,
    substantive_solution_lines,
)

# ---------------------------------------------------------------------------
# is_excluded
# ---------------------------------------------------------------------------


def test_is_excluded_match():
    assert is_excluded("tests/test_foo.py", ["tests/**"])


def test_is_excluded_no_match():
    assert not is_excluded("src/foo.py", ["tests/**", "docs/**"])


# ---------------------------------------------------------------------------
# list_source_files
# ---------------------------------------------------------------------------


def test_list_source_files_glob_and_exclude(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.py").write_text("y = 2\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): pass\n")
    (tmp_path / "README.md").write_text("docs\n")

    files = list_source_files(tmp_path, file_glob="**/*.py", exclude_glob=["tests/**"])
    rels = sorted(str(p.relative_to(tmp_path)) for p in files)
    assert rels == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# sample_seed
# ---------------------------------------------------------------------------


def test_sample_seed_returns_none_for_empty():
    assert sample_seed([], Path("/tmp"), rng=random.Random(0), min_loc=5, max_loc=10) is None


def test_sample_seed_returns_none_for_short_file(tmp_path: Path):
    f = tmp_path / "short.py"
    f.write_text("x = 1\n")
    seed = sample_seed([f], tmp_path, rng=random.Random(0), min_loc=10, max_loc=20)
    assert seed is None


def test_sample_seed_returns_substantive_window(tmp_path: Path):
    f = tmp_path / "real.py"
    f.write_text(
        "\n".join(
            [
                "def add(x, y):",
                "    return x + y",
                "def mul(x, y):",
                "    return x * y",
                "def power(x, n):",
                "    result = 1",
                "    for _ in range(n):",
                "        result *= x",
                "    return result",
                "class Counter:",
                "    def __init__(self):",
                "        self.value = 0",
                "    def inc(self):",
                "        self.value += 1",
            ]
        )
    )
    seed = sample_seed([f], tmp_path, rng=random.Random(0), min_loc=5, max_loc=10)
    assert seed is not None
    assert seed.relative_path == "real.py"
    assert seed.start_line >= 1
    assert seed.end_line > seed.start_line
    # Should contain real code
    assert "def " in seed.text or "class " in seed.text


def test_sample_seed_skips_boring_blocks():
    """A snippet that's 100% imports + blank lines should be rejected."""
    chunk = ["import os", "import sys", "", "# comment", "from typing import Any"]
    assert not _looks_substantive(chunk)


def test_substantive_block_passes():
    chunk = ["def foo():", "    x = 1", "    y = 2", "    return x + y"]
    assert _looks_substantive(chunk)


# ---------------------------------------------------------------------------
# Decontamination
# ---------------------------------------------------------------------------


def test_benchmark_overlap_detects_humaneval_phrase():
    text = "Write a Python function called has_close_elements that takes ..."
    assert has_benchmark_overlap(text)


def test_benchmark_overlap_case_insensitive():
    text = "Write A python Function To do something interesting"
    assert has_benchmark_overlap(text)


def test_benchmark_overlap_negative():
    text = "Implement a queue with a custom eviction strategy"
    assert not has_benchmark_overlap(text)


def test_benchmark_phrases_nonempty():
    assert len(DEFAULT_BENCHMARK_PHRASES) >= 5


def test_benchmark_overlap_does_not_flag_numpy_pandas_idioms():
    """Bare `import numpy as np` / `import pandas as pd` are language idioms,
    not contamination signals. Regression for review finding B1 — including
    them in the phrase list rejected every legitimate data-stack task.
    """
    numpy_solution = "import numpy as np\n\ndef mean(xs):\n    return float(np.mean(xs))\n"
    pandas_solution = "import pandas as pd\n\ndef to_frame(rows):\n    return pd.DataFrame(rows)\n"
    assert not has_benchmark_overlap(numpy_solution)
    assert not has_benchmark_overlap(pandas_solution)


# ---------------------------------------------------------------------------
# substantive_solution_lines + solution_leaks_into_problem
# ---------------------------------------------------------------------------


_LEAKY_SOLUTION = (
    "def luhn_checksum(number):\n"
    "    digits = [int(d) for d in str(number)]\n"
    "    odd_digits = digits[-1::-2]\n"
    "    even_digits = digits[-2::-2]\n"
    "    checksum = sum(odd_digits)\n"
    "    for d in even_digits:\n"
    "        checksum += sum(divmod(d * 2, 10))\n"
    "    return checksum % 10\n"
)


def test_substantive_lines_excludes_signature_and_imports():
    code = "import os\n\ndef f(x):\n    y = x + 1\n    return y\n"
    lines = substantive_solution_lines(code)
    assert "y = x + 1" in lines
    assert all(not ln.startswith("def ") for ln in lines)
    assert all(not ln.startswith("import ") for ln in lines)


def test_substantive_lines_excludes_docstrings_and_trivial_lines():
    code = 'def f(x):\n    """Add one."""\n    pass\n    return x + 100\n'
    lines = substantive_solution_lines(code)
    assert "return x + 100" in lines
    assert "pass" not in lines
    assert all("Add one" not in ln for ln in lines)


def test_substantive_lines_empty_on_syntax_error():
    assert substantive_solution_lines("def broken(:::") == []


def test_leak_detected_when_solution_body_copied_into_problem():
    problem = (
        "Implement luhn_checksum(number). For reference, the algorithm is:\n"
        "digits = [int(d) for d in str(number)]\n"
        "odd_digits = digits[-1::-2]\n"
        "even_digits = digits[-2::-2]\n"
        "checksum = sum(odd_digits)\n"
    )
    assert solution_leaks_into_problem(problem, _LEAKY_SOLUTION)


def test_no_leak_for_clean_problem_with_only_examples():
    problem = (
        "Implement luhn_checksum(number) that returns the Luhn checksum mod 10.\n"
        "Example: luhn_checksum(7992739871) == 3.\n"
        "Example: luhn_checksum(1234567890) == 3.\n"
    )
    assert not solution_leaks_into_problem(problem, _LEAKY_SOLUTION)


def test_leak_threshold_two_lines_is_not_enough():
    """Two leaked lines stay under the default threshold of three."""
    problem = (
        "Implement luhn_checksum(number).\n"
        "digits = [int(d) for d in str(number)]\n"
        "odd_digits = digits[-1::-2]\n"
    )
    assert not solution_leaks_into_problem(problem, _LEAKY_SOLUTION)


def test_small_solution_fully_reproduced_is_a_total_leak():
    """A one-line body echoed in the problem leaks the whole answer even though
    it can never reach three distinct matches.
    """
    solution = "def double(x):\n    return x * 2 + 1\n"
    problem = "Write double(x). The body is simply: return x * 2 + 1\n"
    assert solution_leaks_into_problem(problem, solution)


def test_no_leak_on_solution_syntax_error():
    assert not solution_leaks_into_problem("anything", "def broken(:::")


# ---------------------------------------------------------------------------
# parse_task_response
# ---------------------------------------------------------------------------


_GOOD_RESPONSE = """\
[Problem Description]
Implement add(x, y) that returns x + y.

[Test]
```python
from task_module import add

def test_add_positive():
    assert add(2, 3) == 5
```

[Solution]
```python
def add(x, y):
    return x + y
```
"""


def test_parse_task_response_happy_path():
    parsed = parse_task_response(_GOOD_RESPONSE)
    assert parsed is not None
    assert "Implement add" in parsed.problem
    assert "from task_module import add" in parsed.test_code
    assert "return x + y" in parsed.solution_code
    # Code fences stripped
    assert not parsed.test_code.startswith("```")
    assert not parsed.solution_code.startswith("```")


def test_parse_task_response_returns_none_when_section_missing():
    no_solution = "[Problem Description]\nfoo\n\n[Test]\nbar\n"
    assert parse_task_response(no_solution) is None


def test_parse_task_response_handles_case_insensitive_headers():
    text = (
        "[problem description]\nimpl add\n\n"
        "[TEST]\nfrom task_module import add\ndef test_x():\n    assert add(1, 1) == 2\n\n"
        "[solution]\ndef add(x, y):\n    return x + y\n"
    )
    parsed = parse_task_response(text)
    assert parsed is not None


def test_parse_task_response_handles_unfenced_code():
    text = (
        "[Problem Description]\nDo a thing.\n\n"
        "[Test]\nfrom task_module import x\n\n"
        "[Solution]\nx = 1\n"
    )
    parsed = parse_task_response(text)
    assert parsed is not None
    assert parsed.solution_code == "x = 1"


# ---------------------------------------------------------------------------
# references_task_module
# ---------------------------------------------------------------------------


def test_references_task_module_via_from_import():
    assert references_task_module("from task_module import foo\n")


def test_references_task_module_via_plain_import():
    assert references_task_module("import task_module\n")


def test_references_task_module_negative():
    assert not references_task_module("from typing import Any\n")


def test_references_task_module_nested_import():
    """Import nested inside a function body is still detected via AST."""
    code = "def test_x():\n    from task_module import foo\n    assert foo()\n"
    assert references_task_module(code)


def test_references_task_module_ignores_docstring_mention():
    """A docstring or comment that merely *mentions* the import string
    must NOT trip the gate — only real AST-level imports count.
    Regression for review finding S5.
    """
    docstring_only = (
        "def test_x():\n"
        '    """Example usage:\n'
        "    from task_module import foo\n"
        '    """\n'
        "    assert 1 == 1\n"
    )
    assert not references_task_module(docstring_only)


def test_references_task_module_ignores_syntax_error():
    assert not references_task_module("def broken(:::")


# ---------------------------------------------------------------------------
# extract_task_module_imports — names parsed for the runtime auto-router shim
# ---------------------------------------------------------------------------


def test_extract_imports_single_name():
    code = "from task_module import render_frames\n\ndef test_x(): pass\n"
    assert extract_task_module_imports(code) == ["render_frames"]


def test_extract_imports_multiple_names():
    code = "from task_module import foo, bar, baz\n"
    assert extract_task_module_imports(code) == ["bar", "baz", "foo"]


def test_extract_imports_parenthesized_multiline():
    code = "from task_module import (\n    foo,\n    bar,\n    baz,\n)\n"
    assert extract_task_module_imports(code) == ["bar", "baz", "foo"]


def test_extract_imports_with_alias():
    code = "from task_module import compute as c, helper as h\n"
    assert extract_task_module_imports(code) == ["compute", "helper"]


def test_extract_imports_bare_module_import():
    code = "import task_module\n\ndef test_x(): task_module.foo()\n"
    assert extract_task_module_imports(code) == []


def test_extract_imports_negative():
    code = "from typing import Any\nimport os\n"
    assert extract_task_module_imports(code) == []


def test_extract_imports_handles_syntax_error():
    assert extract_task_module_imports("def broken(:::") == []


def test_extract_imports_dedup_across_statements():
    code = "from task_module import foo\nfrom task_module import foo, bar\n"
    assert extract_task_module_imports(code) == ["bar", "foo"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
