import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import _detect_log_parser_type


# ---------- Django detection ("runtests.py" in string) ----------

DJANGO_CASES = [
    ("runtests.py", "django"),
    ("python runtests.py", "django"),
    ("python runtests.py --settings=test", "django"),
    ("./runtests.py", "django"),
    ("/path/to/runtests.py", "django"),
    ("cd django && python runtests.py", "django"),
    ("python3 runtests.py --verbosity=2", "django"),
    ("runtests.py --parallel", "django"),
    ("env DJANGO=1 runtests.py", "django"),
    ("bash -c 'runtests.py'", "django"),
    ("  runtests.py  ", "django"),
    ("ABC runtests.py DEF", "django"),
    ("runtests.py runtests.py", "django"),
    ("FOOruntests.pyBAR", "django"),
    ("runtests.pyc && runtests.py", "django"),
    ("xruntests.py", "django"),
    ("runtests.pyz", "django"),
    ("echo runtests.py | bash", "django"),
    ("python -m runtests.py", "django"),
    ("nohup runtests.py &", "django"),
    ("timeout 300 runtests.py", "django"),
    ("python tests/runtests.py --parallel 4", "django"),
    ("PYTHONPATH=. runtests.py", "django"),
    ("runtests.py tests.test_models", "django"),
    ("python runtests.py --noinput", "django"),
]


@pytest.mark.parametrize("cmd, expected", DJANGO_CASES, ids=[f"django-{i}" for i in range(len(DJANGO_CASES))])
def test_django_detection(cmd: str, expected: str) -> None:
    assert _detect_log_parser_type(cmd) == expected


# ---------- Sympy detection ("bin/test" in string) ----------

SYMPY_CASES = [
    ("bin/test", "sympy"),
    ("python bin/test", "sympy"),
    ("python bin/test -v", "sympy"),
    ("./bin/test", "sympy"),
    ("/usr/bin/test", "sympy"),
    ("cd sympy && bin/test", "sympy"),
    ("bin/test sympy/core", "sympy"),
    ("bin/test --timeout=300", "sympy"),
    ("  bin/test  ", "sympy"),
    ("ABCbin/testDEF", "sympy"),
    ("xbin/test", "sympy"),
    ("bin/testy", "sympy"),
    ("bin/test bin/test", "sympy"),
    ("echo bin/test | bash", "sympy"),
    ("python3 bin/test -k test_foo", "sympy"),
    ("timeout 600 bin/test", "sympy"),
    ("bash -c 'bin/test'", "sympy"),
    ("PYTHONPATH=. bin/test", "sympy"),
    ("bin/test --split=1/3", "sympy"),
    ("bin/test --no-colors", "sympy"),
]


@pytest.mark.parametrize("cmd, expected", SYMPY_CASES, ids=[f"sympy-{i}" for i in range(len(SYMPY_CASES))])
def test_sympy_detection(cmd: str, expected: str) -> None:
    assert _detect_log_parser_type(cmd) == expected


# ---------- Django takes priority over sympy ----------

PRIORITY_CASES = [
    ("runtests.py bin/test", "django"),
    ("bin/test runtests.py", "django"),
    ("runtests.py && bin/test", "django"),
    ("python runtests.py && python bin/test", "django"),
]


@pytest.mark.parametrize("cmd, expected", PRIORITY_CASES, ids=[f"priority-{i}" for i in range(len(PRIORITY_CASES))])
def test_django_priority_over_sympy(cmd: str, expected: str) -> None:
    assert _detect_log_parser_type(cmd) == expected


# ---------- Pytest fallback (everything else) ----------

PYTEST_CASES = [
    ("pytest", "pytest"),
    ("python -m pytest", "pytest"),
    ("pytest tests/", "pytest"),
    ("pytest -x --tb=short", "pytest"),
    ("pytest --cov=mypackage", "pytest"),
    ("python -m pytest -v", "pytest"),
    ("tox -e py39", "pytest"),
    ("nox -s tests", "pytest"),
    ("make test", "pytest"),
    ("", "pytest"),
    ("python setup.py test", "pytest"),
    ("nosetests", "pytest"),
    ("unittest discover", "pytest"),
    ("   ", "pytest"),
    ("echo hello", "pytest"),
    ("python test_something.py", "pytest"),
    ("./run_tests.sh", "pytest"),
    ("bin/run_tests", "pytest"),
    ("tests/run.py", "pytest"),
    ("runtests", "pytest"),
    ("runtest.py", "pytest"),
    ("runtests.p", "pytest"),
    ("RUNTESTS.PY", "pytest"),
    ("Runtests.py", "pytest"),
    ("runtests.PY", "pytest"),
    ("BIN/TEST", "pytest"),
    ("Bin/Test", "pytest"),
    ("bin/Test", "pytest"),
    ("bin\\test", "pytest"),
    ("bin_test", "pytest"),
    ("bintest", "pytest"),
    ("bin /test", "pytest"),
    ("bin/ test", "pytest"),
    ("test", "pytest"),
    ("bin", "pytest"),
    ("runtests", "pytest"),
    ("12345", "pytest"),
    ("!@#$%^&*()", "pytest"),
    ("null", "pytest"),
    ("None", "pytest"),
    ("true", "pytest"),
    ("false", "pytest"),
]


@pytest.mark.parametrize("cmd, expected", PYTEST_CASES, ids=[f"pytest-{i}" for i in range(len(PYTEST_CASES))])
def test_pytest_fallback(cmd: str, expected: str) -> None:
    assert _detect_log_parser_type(cmd) == expected
