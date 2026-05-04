from __future__ import annotations

import pytest

from helpers import extract_code_block


class TestExtractNone:
    def test_none_input(self):
        assert extract_code_block(None) is None

    def test_empty_string(self):
        assert extract_code_block("") is None

    def test_whitespace_only(self):
        assert extract_code_block("   \n\t  ") is None

    def test_no_code_block(self):
        assert extract_code_block("Just some plain text without any code.") is None

    def test_single_backtick(self):
        assert extract_code_block("`inline code`") is None

    def test_double_backtick(self):
        assert extract_code_block("``not a block``") is None


class TestExtractBasicBlocks:
    def test_python_fenced(self):
        text = "```python\nprint('hi')\n```"
        assert extract_code_block(text) == "print('hi')"

    def test_no_language_tag(self):
        text = "```\nprint('hi')\n```"
        assert extract_code_block(text) == "print('hi')"

    def test_language_tag_js(self):
        text = "```javascript\nconsole.log('hi');\n```"
        assert extract_code_block(text) == "console.log('hi');"

    def test_language_tag_bash(self):
        text = "```bash\necho hello\n```"
        assert extract_code_block(text) == "echo hello"

    def test_language_tag_py(self):
        text = "```py\nx = 1\n```"
        assert extract_code_block(text) == "x = 1"

    def test_multiline_code(self):
        text = "```python\nimport os\nimport sys\nprint(os.getcwd())\n```"
        result = extract_code_block(text)
        assert "import os" in result
        assert "import sys" in result
        assert "print(os.getcwd())" in result

    def test_strips_whitespace(self):
        text = "```python\n  \n  code  \n  \n```"
        result = extract_code_block(text)
        assert result == "code"


class TestExtractWithSurroundingText:
    def test_text_before(self):
        text = "Here is the code:\n```python\nprint('hi')\n```"
        assert extract_code_block(text) == "print('hi')"

    def test_text_after(self):
        text = "```python\nprint('hi')\n```\nThat was the code."
        assert extract_code_block(text) == "print('hi')"

    def test_text_before_and_after(self):
        text = "Preamble.\n```python\ncode()\n```\nPostamble."
        assert extract_code_block(text) == "code()"

    def test_markdown_headers(self):
        text = "# Title\n\nSome text.\n\n```python\nx = 42\n```\n\n## End"
        assert extract_code_block(text) == "x = 42"

    def test_multiple_blocks_returns_first(self):
        text = "```python\nfirst()\n```\ntext\n```python\nsecond()\n```"
        assert extract_code_block(text) == "first()"


class TestExtractWorkloadPatterns:
    def test_full_workload_script(self):
        text = """Here is a workload:

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
        result = extract_code_block(text)
        assert "import timeit" in result
        assert "def setup():" in result
        assert "def workload():" in result
        assert "timeit.repeat" in result
        assert 'print("Mean:"' in result
        assert 'print("Std Dev:"' in result

    def test_workload_with_pandas(self):
        code = "import timeit\nimport pandas as pd\n\ndef setup():\n    pass\n\ndef workload():\n    pd.DataFrame()\n"
        text = f"```python\n{code}```"
        result = extract_code_block(text)
        assert "import pandas as pd" in result

    @pytest.mark.parametrize("lib", [
        "numpy", "scipy", "pandas", "sklearn", "matplotlib",
        "xarray", "sympy", "dask", "astropy",
    ])
    def test_workload_importing_various_libs(self, lib):
        code = f"import {lib}\nprint('done')"
        text = f"```python\n{code}\n```"
        result = extract_code_block(text)
        assert f"import {lib}" in result


class TestExtractEdgeCases:
    def test_backticks_inside_code(self):
        text = "```python\nx = '```not closing```'\nprint(x)\n```"
        result = extract_code_block(text)
        assert result is not None

    def test_empty_code_block(self):
        text = "```python\n\n```"
        result = extract_code_block(text)
        assert result == "" or result is None

    def test_only_whitespace_in_block(self):
        text = "```python\n   \n   \n```"
        result = extract_code_block(text)
        assert result == "" or result is None

    def test_code_with_triple_quotes(self):
        text = '```python\nx = """triple\nquoted"""\n```'
        result = extract_code_block(text)
        assert "triple" in result

    def test_newlines_in_code(self):
        text = "```python\n\n\ncode()\n\n\n```"
        result = extract_code_block(text)
        assert "code()" in result

    def test_tabs_in_code(self):
        text = "```python\ndef f():\n\treturn 1\n```"
        result = extract_code_block(text)
        assert "return 1" in result

    def test_unicode_in_code(self):
        text = "```python\n# コメント\nprint('日本語')\n```"
        result = extract_code_block(text)
        assert "日本語" in result

    def test_very_long_code(self):
        lines = [f"x_{i} = {i}" for i in range(500)]
        code = "\n".join(lines)
        text = f"```python\n{code}\n```"
        result = extract_code_block(text)
        assert "x_0 = 0" in result
        assert "x_499 = 499" in result

    def test_code_with_regex(self):
        text = "```python\nimport re\nre.findall(r'```', text)\n```"
        result = extract_code_block(text)
        assert result is not None

    def test_windows_line_endings(self):
        text = "```python\r\nprint('hi')\r\n```"
        result = extract_code_block(text)
        assert "print" in result


LANGUAGE_TAGS = [
    "python", "py", "python3", "javascript", "js", "typescript", "ts",
    "bash", "sh", "shell", "zsh", "java", "c", "cpp", "c++", "csharp",
    "go", "rust", "ruby", "php", "sql", "yaml", "json", "xml", "html",
    "css", "r", "R", "scala", "kotlin", "swift", "objective-c",
    "perl", "lua", "haskell", "elixir", "clojure", "dart",
]


class TestExtractLanguageTags:
    @pytest.mark.parametrize("tag", LANGUAGE_TAGS)
    def test_various_language_tags(self, tag):
        text = f"```{tag}\ncode_here()\n```"
        assert extract_code_block(text) == "code_here()"

    def test_tag_with_extra_spaces(self):
        text = "```python \ncode()\n```"
        result = extract_code_block(text)
        assert result == "code()"

    def test_uppercase_tag(self):
        text = "```PYTHON\ncode()\n```"
        result = extract_code_block(text)
        assert result == "code()"


PARAMETRIZED_BLOCKS = [
    ("single statement", "x = 1", "x = 1"),
    ("function def", "def f():\n    return 1", "def f():\n    return 1"),
    ("class def", "class Foo:\n    pass", "class Foo:\n    pass"),
    ("import only", "import os", "import os"),
    ("multiline import", "import os\nimport sys\nimport json", "import os"),
    ("decorator", "@pytest.mark.parametrize\ndef test():\n    pass", "@pytest.mark.parametrize"),
    ("with statement", "with open('f') as fp:\n    data = fp.read()", "with open"),
    ("try/except", "try:\n    x = 1\nexcept:\n    pass", "try:"),
    ("list comprehension", "result = [x**2 for x in range(10)]", "result = [x**2"),
    ("dict comprehension", "d = {k: v for k, v in items}", "d = {k: v"),
    ("lambda", "fn = lambda x: x + 1", "fn = lambda"),
    ("f-string", "msg = f'Hello {name}'", "msg = f'Hello"),
    ("raw string", "pattern = r'\\d+'", "pattern = r'"),
    ("bytes literal", "data = b'\\x00\\x01'", "data = b'"),
    ("ellipsis", "def stub(): ...", "def stub(): ..."),
    ("walrus operator", "if (n := len(arr)) > 10: pass", "if (n := len"),
    ("match statement", "match cmd:\n    case 'q': quit()", "match cmd:"),
    ("yield", "def gen():\n    yield 1", "yield 1"),
    ("async def", "async def handler():\n    await resp", "async def"),
    ("global statement", "global x\nx = 42", "global x"),
]


class TestExtractParametrizedContent:
    @pytest.mark.parametrize(
        "name,code,expected_substr",
        PARAMETRIZED_BLOCKS,
        ids=[p[0] for p in PARAMETRIZED_BLOCKS],
    )
    def test_extract_various_python_constructs(self, name, code, expected_substr):
        text = f"```python\n{code}\n```"
        result = extract_code_block(text)
        assert expected_substr in result


REAL_WORLD_RESPONSES = [
    (
        "Sure! Here's the workload:\n\n```python\nimport timeit\nruntimes = timeit.repeat(lambda: 1+1, number=100, repeat=5)\n```\n\nLet me know!",
        "import timeit",
    ),
    (
        "```\nimport numpy\n```",
        "import numpy",
    ),
    (
        "I'll generate a workload.\n\n```python\nimport statistics\nimport timeit\n\ndef setup():\n    pass\n\ndef workload():\n    sum(range(1000))\n\nruntimes = timeit.repeat(workload, number=10, repeat=5, setup=setup)\nprint('Mean:', statistics.mean(runtimes))\nprint('Std Dev:', statistics.stdev(runtimes))\n```\n\nThis should work well.",
        "def workload():",
    ),
    (
        "The optimization targets numpy's sort function.\n\n```python\nimport numpy as np\nimport timeit\nimport statistics\n\ndef setup():\n    global data\n    np.random.seed(0)\n    data = np.random.rand(10000)\n\ndef workload():\n    np.sort(data.copy())\n\nruntimes = timeit.repeat(workload, number=100, repeat=10, setup=setup)\nprint('Mean:', statistics.mean(runtimes))\nprint('Std Dev:', statistics.stdev(runtimes))\n```",
        "np.sort(data.copy())",
    ),
]


class TestExtractRealWorldResponses:
    @pytest.mark.parametrize(
        "response,expected_substr",
        REAL_WORLD_RESPONSES,
        ids=[f"response_{i}" for i in range(len(REAL_WORLD_RESPONSES))],
    )
    def test_real_llm_responses(self, response, expected_substr):
        result = extract_code_block(response)
        assert result is not None
        assert expected_substr in result

    def test_no_code_in_refusal(self):
        text = "I cannot generate a workload for this change because the diff is too complex."
        assert extract_code_block(text) is None

    def test_incomplete_block(self):
        text = "```python\nprint('hi')"
        result = extract_code_block(text)
        assert result is None

    def test_only_opening_fence(self):
        text = "```python"
        assert extract_code_block(text) is None

    def test_only_closing_fence(self):
        text = "```"
        assert extract_code_block(text) is None


SPECIAL_CHARACTERS = [
    ("backslashes", "path = 'C:\\\\Users\\\\test'", "C:\\\\Users"),
    ("dollar signs", "cost = '$100'", "$100"),
    ("angle brackets", "x = 1 < 2 and 3 > 2", "1 < 2"),
    ("ampersands", "a & b", "a & b"),
    ("pipes", "a | b", "a | b"),
    ("semicolons", "a = 1; b = 2", "a = 1; b = 2"),
    ("parentheses nested", "f(g(h(x)))", "f(g(h(x)))"),
    ("square brackets nested", "a[b[c[0]]]", "a[b[c[0]]]"),
    ("curly braces nested", "{1: {2: {3: 4}}}", "{1: {2: {3: 4}}}"),
    ("at sign", "@decorator\ndef f(): pass", "@decorator"),
    ("hash in string", "s = '#not a comment'", "#not a comment"),
    ("percent formatting", "s = '%d items' % n", "'%d items'"),
    ("star expressions", "a, *b, c = [1,2,3,4]", "a, *b, c"),
    ("double star", "d = {**a, **b}", "d = {**a, **b}"),
    ("tilde", "mask = ~arr.isnan()", "~arr"),
    ("caret", "x = a ^ b", "a ^ b"),
]


class TestExtractSpecialCharacters:
    @pytest.mark.parametrize(
        "name,code,expected_substr",
        SPECIAL_CHARACTERS,
        ids=[s[0] for s in SPECIAL_CHARACTERS],
    )
    def test_special_chars_preserved(self, name, code, expected_substr):
        text = f"```python\n{code}\n```"
        result = extract_code_block(text)
        assert expected_substr in result


WHITESPACE_PATTERNS = [
    ("leading newlines", "\n\n\ncode()\n", "code()"),
    ("trailing newlines", "code()\n\n\n", "code()"),
    ("leading spaces", "    code()", "code()"),
    ("mixed indentation", "if True:\n    x = 1\n\tpass", "if True:"),
    ("blank lines between", "a = 1\n\n\nb = 2", "a = 1"),
    ("only spaces between lines", "a = 1\n   \nb = 2", "a = 1"),
]


class TestExtractWhitespaceHandling:
    @pytest.mark.parametrize(
        "name,code,expected_substr",
        WHITESPACE_PATTERNS,
        ids=[w[0] for w in WHITESPACE_PATTERNS],
    )
    def test_whitespace_variants(self, name, code, expected_substr):
        text = f"```python\n{code}\n```"
        result = extract_code_block(text)
        assert expected_substr in result
