from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from swefficiency.workload.run_synthetic_generation import (
    CONTEXT_MSG,
    SYSTEM_MSG,
    WORKLOAD_GENERATION_DIR,
    extract_code_block,
    main,
    worker_function,
)

SAMPLE_PATCH = (
    "diff --git a/numpy/core/fromnumeric.py b/numpy/core/fromnumeric.py\n"
    "index abc1234..def5678 100644\n"
    "--- a/numpy/core/fromnumeric.py\n"
    "+++ b/numpy/core/fromnumeric.py\n"
    "@@ -10,6 +10,7 @@\n"
    " import numpy as np\n"
    "+# optimized path\n"
    " def sort(a):\n"
)

SAMPLE_PATCH_TWO_FILES = (
    "diff --git a/lib/foo.py b/lib/foo.py\n"
    "index 111..222 100644\n"
    "--- a/lib/foo.py\n"
    "+++ b/lib/foo.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
    "diff --git a/lib/bar.py b/lib/bar.py\n"
    "index 333..444 100644\n"
    "--- a/lib/bar.py\n"
    "+++ b/lib/bar.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


def make_datum(
    instance_id: str = "numpy__numpy-12345",
    repo: str = "numpy/numpy",
    base_commit: str = "abc123def456",
    patch: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": base_commit,
        "patch": patch or SAMPLE_PATCH,
        **extra,
    }


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

SAMPLE_LLM_RESPONSE_NO_BLOCK = "I cannot generate a workload for this change."

SAMPLE_CODE_BLOCK = """import timeit
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
print("Std Dev:", statistics.stdev(runtimes))"""


def make_completion_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp
