"""~1000 parametrized tests for detect_test_cmd()."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_test_cmd

PYTEST_TF = "pytest {test_files}"

# ═══════════════════════════════════════════════════════════════════════════
# Helper to write files in tmp_path
# ═══════════════════════════════════════════════════════════════════════════

def _write(tmp_path: Path, relpath: str, content: str) -> Path:
    p = tmp_path / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _mkdir(tmp_path: Path, relpath: str) -> Path:
    p = tmp_path / relpath
    p.mkdir(parents=True, exist_ok=True)
    return p


# ═══════════════════════════════════════════════════════════════════════════
# 1. pyproject.toml with [tool.pytest.ini_options] → "pytest {test_files}"
#    ~200 tests
# ═══════════════════════════════════════════════════════════════════════════

PYPROJECT_CASES = []

# 1a. Bare ini_options section (50 cases with minor variations)
for i in range(50):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_bare_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
# variation {i}
"""},
        PYTEST_TF,
        id=f"pyproject-bare-ini_options-{i}",
    ))

# 1b. ini_options with testpaths
_testpath_variants = [
    'testpaths = ["tests"]',
    'testpaths = ["tests", "integration"]',
    'testpaths = ["src/tests"]',
    'testpaths = ["test"]',
    'testpaths = ["unit_tests"]',
    'testpaths = ["tests/unit", "tests/integration"]',
    "testpaths = ['tests']",
    'testpaths = ["functional_tests", "regression"]',
    'testpaths = ["spec"]',
    'testpaths = ["t"]',
    'testpaths = ["checks"]',
    'testpaths = ["qa"]',
    'testpaths = ["verification"]',
    'testpaths = ["test_suite"]',
    'testpaths = ["tests/smoke"]',
    'testpaths = ["tests/e2e"]',
    'testpaths = ["tests/acceptance"]',
    'testpaths = ["tests/perf"]',
    'testpaths = ["tests/api"]',
    'testpaths = ["tests/ui"]',
]
for i, tp in enumerate(_testpath_variants):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_testpaths_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
{tp}
"""},
        PYTEST_TF,
        id=f"pyproject-testpaths-{i}",
    ))

# 1c. ini_options with addopts
_addopts_variants = [
    'addopts = "-v"',
    'addopts = "--strict-markers"',
    'addopts = "-ra -q"',
    'addopts = "--tb=short"',
    'addopts = "--cov=mypackage"',
    'addopts = "--no-header"',
    'addopts = "--maxfail=5"',
    'addopts = "-x --timeout=30"',
    'addopts = "--durations=10"',
    'addopts = "--color=yes"',
    'addopts = "-p no:warnings"',
    'addopts = "--import-mode=importlib"',
    'addopts = "--doctest-modules"',
    'addopts = "--pdb"',
    'addopts = "-k not slow"',
    'addopts = "--benchmark-disable"',
    'addopts = "--randomly-seed=1234"',
    'addopts = "--hypothesis-seed=0"',
    'addopts = "--reruns 3"',
    'addopts = "--capture=no"',
    'addopts = "-s -vvv"',
    'addopts = "--lf"',
    'addopts = "--ff"',
    'addopts = "--nf"',
    'addopts = "--sw"',
]
for i, ao in enumerate(_addopts_variants):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_addopts_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
{ao}
"""},
        PYTEST_TF,
        id=f"pyproject-addopts-{i}",
    ))

# 1d. ini_options with markers
_marker_variants = [
    'markers = ["slow: marks tests as slow"]',
    'markers = ["integration", "unit"]',
    'markers = ["smoke: smoke tests"]',
    'markers = ["e2e: end to end"]',
    'markers = ["perf: performance"]',
    'markers = ["wip: work in progress"]',
    'markers = ["nightly"]',
    'markers = ["serial: must run serially"]',
    'markers = ["gpu: requires gpu"]',
    'markers = ["network: needs network"]',
    'markers = ["db: needs database"]',
    'markers = ["slow", "fast"]',
    'markers = ["regression"]',
    'markers = ["flaky"]',
    'markers = ["xfail_strict"]',
]
for i, mk in enumerate(_marker_variants):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_markers_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
{mk}
"""},
        PYTEST_TF,
        id=f"pyproject-markers-{i}",
    ))

# 1e. ini_options with minversion / filterwarnings / log_cli etc
_misc_ini_variants = [
    'minversion = "6.0"',
    'minversion = "7.0"',
    'minversion = "5.0"',
    'filterwarnings = ["error", "ignore::DeprecationWarning"]',
    'filterwarnings = ["ignore::PendingDeprecationWarning"]',
    'filterwarnings = ["error::UserWarning"]',
    'log_cli = true',
    'log_cli = false',
    'log_cli_level = "INFO"',
    'log_cli_level = "DEBUG"',
    'log_format = "%(asctime)s %(levelname)s %(message)s"',
    'console_output_style = "progress"',
    'console_output_style = "classic"',
    'norecursedirs = ["build", "dist"]',
    'python_files = ["test_*.py", "check_*.py"]',
    'python_classes = ["Test", "Describe"]',
    'python_functions = ["test_", "check_"]',
    'xfail_strict = true',
    'required_plugins = ["pytest-cov"]',
    'cache_dir = ".pytest_cache"',
]
for i, misc in enumerate(_misc_ini_variants):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_misc_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
{misc}
"""},
        PYTEST_TF,
        id=f"pyproject-misc-ini-{i}",
    ))

# 1f. ini_options combined with other tool sections
_other_tool_sections = [
    "[tool.black]\nline-length = 88",
    "[tool.isort]\nprofile = \"black\"",
    "[tool.mypy]\nstrict = true",
    "[tool.ruff]\nline-length = 120",
    "[tool.coverage.run]\nsource = [\"mypackage\"]",
    "[tool.coverage.report]\nexclude_lines = [\"pragma: no cover\"]",
    "[tool.setuptools]\npackages = [\"mypackage\"]",
    "[tool.poetry]\nname = \"mypackage\"",
    "[tool.pdm]\nversion = \"1.0\"",
    "[tool.hatch.version]\npath = \"src/__about__.py\"",
    "[tool.bandit]\nskips = [\"B101\"]",
    "[tool.pylint.messages_control]\ndisable = [\"C0114\"]",
    "[tool.tox]\nlegacy_tox_ini = \"[tox]\"",
    "[tool.flake8]\nmax-line-length = 120",
    "[tool.pyright]\ntypeCheckingMode = \"basic\"",
]
for i, section in enumerate(_other_tool_sections):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_other_tool_{i}",
        {"pyproject.toml": f"""\
{section}

[tool.pytest.ini_options]
addopts = "-v"
"""},
        PYTEST_TF,
        id=f"pyproject-with-other-tool-{i}",
    ))

# 1g. ini_options with combination of multiple settings
for i in range(20):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_combo_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
addopts = "-v --tb=short"
testpaths = ["tests"]
markers = ["slow: slow tests"]
minversion = "6.0"
# combo variation {i}
"""},
        PYTEST_TF,
        id=f"pyproject-combo-{i}",
    ))

# 1h. Empty ini_options section
for i in range(10):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_empty_ini_{i}",
        {"pyproject.toml": f"""\
[tool.pytest.ini_options]
"""},
        PYTEST_TF,
        id=f"pyproject-empty-ini_options-{i}",
    ))

# 1i. ini_options with project section present
for i in range(10):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_with_project_{i}",
        {"pyproject.toml": f"""\
[project]
name = "mypkg-{i}"
version = "0.{i}.0"

[tool.pytest.ini_options]
addopts = "-q"
"""},
        PYTEST_TF,
        id=f"pyproject-with-project-section-{i}",
    ))

# 1j. ini_options with build-system present
for i in range(5):
    PYPROJECT_CASES.append(pytest.param(
        f"pyproject_with_build_{i}",
        {"pyproject.toml": f"""\
[build-system]
requires = ["setuptools>={60+i}"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
"""},
        PYTEST_TF,
        id=f"pyproject-with-build-system-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", PYPROJECT_CASES)
def test_pyproject_pytest_config(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. setup.cfg with [tool:pytest] → "pytest {test_files}"  (~150)
# ═══════════════════════════════════════════════════════════════════════════

SETUP_CFG_CASES = []

# 2a. Bare [tool:pytest] section
for i in range(30):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_bare_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
# bare section {i}
"""},
        PYTEST_TF,
        id=f"setup-cfg-bare-{i}",
    ))

# 2b. [tool:pytest] with addopts
_cfg_addopts = [
    "addopts = -v",
    "addopts = --strict-markers",
    "addopts = -ra -q",
    "addopts = --tb=short",
    "addopts = --cov=mypackage",
    "addopts = --no-header -rN",
    "addopts = --maxfail=5",
    "addopts = -x --timeout=30",
    "addopts = --durations=10",
    "addopts = --color=yes",
    "addopts = -p no:warnings",
    "addopts = --import-mode=importlib",
    "addopts = --doctest-modules",
    "addopts = --pdb",
    "addopts = -k not slow",
    "addopts = --benchmark-disable",
    "addopts = --randomly-seed=1234",
    "addopts = --reruns 3",
    "addopts = --capture=no",
    "addopts = -s -vvv",
]
for i, ao in enumerate(_cfg_addopts):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_addopts_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
{ao}
"""},
        PYTEST_TF,
        id=f"setup-cfg-addopts-{i}",
    ))

# 2c. [tool:pytest] with testpaths
_cfg_testpaths = [
    "testpaths = tests",
    "testpaths = tests integration",
    "testpaths = src/tests",
    "testpaths = test",
    "testpaths = tests/unit tests/integration",
    "testpaths =\n    tests\n    integration",
    "testpaths =\n    tests",
    "testpaths = functional_tests",
    "testpaths = spec",
    "testpaths = t",
]
for i, tp in enumerate(_cfg_testpaths):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_testpaths_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
{tp}
"""},
        PYTEST_TF,
        id=f"setup-cfg-testpaths-{i}",
    ))

# 2d. [tool:pytest] with markers
_cfg_markers = [
    "markers =\n    slow: slow tests\n    integration: integration tests",
    "markers =\n    smoke: smoke tests",
    "markers =\n    e2e: end to end\n    unit: unit test",
    "markers =\n    perf: performance test",
    "markers =\n    wip\n    nightly",
    "markers = slow",
    "markers = integration",
    "markers = smoke",
    "markers = flaky",
    "markers = regression",
]
for i, mk in enumerate(_cfg_markers):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_markers_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
{mk}
"""},
        PYTEST_TF,
        id=f"setup-cfg-markers-{i}",
    ))

# 2e. [tool:pytest] with filterwarnings
_cfg_filters = [
    "filterwarnings =\n    error\n    ignore::DeprecationWarning",
    "filterwarnings =\n    ignore::PendingDeprecationWarning",
    "filterwarnings = error",
    "filterwarnings =\n    error::UserWarning\n    ignore::FutureWarning",
    "filterwarnings = ignore",
]
for i, fw in enumerate(_cfg_filters):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_filters_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
{fw}
"""},
        PYTEST_TF,
        id=f"setup-cfg-filterwarnings-{i}",
    ))

# 2f. [tool:pytest] with misc options
_cfg_misc = [
    "minversion = 6.0",
    "minversion = 7.0",
    "minversion = 5.0",
    "log_cli = true",
    "log_cli = false",
    "log_cli_level = INFO",
    "log_cli_level = DEBUG",
    "console_output_style = progress",
    "norecursedirs = build dist",
    "python_files = test_*.py check_*.py",
    "python_classes = Test Describe",
    "python_functions = test_ check_",
    "xfail_strict = true",
    "cache_dir = .pytest_cache",
    "required_plugins = pytest-cov",
]
for i, misc in enumerate(_cfg_misc):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_misc_{i}",
        {"setup.cfg": f"""\
[tool:pytest]
{misc}
"""},
        PYTEST_TF,
        id=f"setup-cfg-misc-{i}",
    ))

# 2g. [tool:pytest] with other sections present
_cfg_other = [
    "[metadata]\nname = mypkg",
    "[options]\npackages = find:",
    "[options.packages.find]\nwhere = src",
    "[bdist_wheel]\nuniversal = 1",
    "[flake8]\nmax-line-length = 120",
    "[isort]\nprofile = black",
    "[mypy]\nstrict = True",
    "[options.extras_require]\ndev = pytest",
    "[options.entry_points]\nconsole_scripts =\n    mypkg = mypkg.cli:main",
    "[tool:isort]\nprofile = black",
]
for i, other in enumerate(_cfg_other):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_other_sections_{i}",
        {"setup.cfg": f"""\
{other}

[tool:pytest]
addopts = -v
"""},
        PYTEST_TF,
        id=f"setup-cfg-with-other-sections-{i}",
    ))

# 2h. Combo setup.cfg
for i in range(20):
    SETUP_CFG_CASES.append(pytest.param(
        f"setup_cfg_combo_{i}",
        {"setup.cfg": f"""\
[metadata]
name = pkg{i}

[tool:pytest]
addopts = -v --tb=short
testpaths = tests
markers =
    slow: slow tests
"""},
        PYTEST_TF,
        id=f"setup-cfg-combo-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", SETUP_CFG_CASES)
def test_setup_cfg_pytest(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 3. tox.ini [testenv] commands → (~250)
# ═══════════════════════════════════════════════════════════════════════════

TOX_CASES = []

# 3a. Simple pytest in commands → "pytest {test_files}"
_tox_pytest_variants = [
    "pytest",
    "pytest tests/",
    "pytest tests/ -v",
    "pytest -x tests/",
    "pytest --tb=short",
    "pytest -ra",
    "pytest -q",
    "pytest --cov=mypackage tests/",
    "pytest {posargs}",
    "pytest {posargs:tests}",
    "pytest tests/ {posargs}",
    "pytest -v {posargs}",
    "pytest --no-header -rN",
    "pytest --maxfail=5 tests/",
    "pytest -x --timeout=30",
    "pytest --durations=10",
    "pytest --color=yes tests/",
    "pytest -p no:warnings",
    "pytest --import-mode=importlib",
    "pytest --doctest-modules",
    "pytest -k 'not slow'",
    "pytest --benchmark-disable",
    "pytest --randomly-seed=1234",
    "pytest --reruns 3",
    "pytest --capture=no tests/",
    "pytest -s -vvv",
    "pytest --lf",
    "pytest --ff",
    "pytest --nf",
    "pytest --sw",
    "pytest --co",
    "pytest --collect-only",
    "pytest -n auto",
    "pytest -n 4",
    "pytest --dist loadscope",
    "pytest tests/unit",
    "pytest tests/integration",
    "pytest tests/functional",
    "pytest tests/e2e",
    "pytest tests/smoke",
    "python -m pytest",
    "python -m pytest tests/",
    "python -m pytest -v",
    "python -m pytest {posargs}",
    "python -m pytest tests/ -x",
    "pytest tests/ --cov=src --cov-report=html",
    "pytest -W error::DeprecationWarning",
    "pytest tests/ -v --tb=long",
    "pytest tests/ -ra -q",
    "pytest tests/ --strict-markers",
]
for i, cmd in enumerate(_tox_pytest_variants):
    TOX_CASES.append(pytest.param(
        f"tox_pytest_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        PYTEST_TF,
        id=f"tox-pytest-cmd-{i}",
    ))

# 3b. pytest with deps section present
for i in range(20):
    TOX_CASES.append(pytest.param(
        f"tox_pytest_with_deps_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py3{i % 10 + 8}

[testenv]
deps = pytest
    coverage
commands = pytest tests/ -v
"""},
        PYTEST_TF,
        id=f"tox-pytest-with-deps-{i}",
    ))

# 3c. pytest with setenv / passenv etc
for i in range(15):
    TOX_CASES.append(pytest.param(
        f"tox_pytest_with_env_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
setenv =
    PYTHONDONTWRITEBYTECODE = 1
passenv = HOME
deps = pytest
commands = pytest tests/ --tb=short
"""},
        PYTEST_TF,
        id=f"tox-pytest-with-env-{i}",
    ))

# 3d. tox with non-pytest command that contains "pytest" substring
_tox_contains_pytest = [
    "run-pytest-wrapper tests/",
    "invoke pytest-run",
    "make pytest",
    "bash -c 'pytest tests/'",
    "sh -c 'pytest'",
    "coverage run -m pytest",
    "coverage run -m pytest tests/",
    "python -c 'import pytest; pytest.main()'",
    "nox -s pytest",
    "tox-pytest-bridge run",
]
for i, cmd in enumerate(_tox_contains_pytest):
    TOX_CASES.append(pytest.param(
        f"tox_contains_pytest_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        PYTEST_TF,
        id=f"tox-contains-pytest-{i}",
    ))

# 3e. Non-pytest commands (no "pytest" substring) that get cleaned
_tox_non_pytest = [
    ("nosetests tests/", "nosetests tests/"),
    ("python -m unittest discover", "python -m unittest discover"),
    ("trial tests/", "trial tests/"),
    ("python setup.py test", "python setup.py test"),
    ("make test", "make test"),
    ("invoke test", "invoke test"),
    ("tox-run test", "tox-run test"),
    ("green tests/", "green tests/"),
    ("nose2", "nose2"),
    ("python -m nose", "python -m nose"),
    ("stestr run", "stestr run"),
    ("testr run", "testr run"),
    ("python runtests.py", "python runtests.py"),
    ("python -m twisted.trial", "python -m twisted.trial"),
    ("avocado run tests/", "avocado run tests/"),
]
for i, (cmd, expected) in enumerate(_tox_non_pytest):
    TOX_CASES.append(pytest.param(
        f"tox_non_pytest_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        expected,
        id=f"tox-non-pytest-cmd-{i}",
    ))

# 3f. Non-pytest commands with tox substitutions that get stripped
_tox_non_pytest_subs = [
    ("nosetests {posargs}", "nosetests"),
    ("python -m unittest {posargs}", "python -m unittest"),
    ("trial {posargs:tests/}", "trial"),
    ("green {posargs}", "green"),
    ("nose2 {posargs}", "nose2"),
    ("stestr run {posargs}", "stestr run"),
    ("python runtests.py {posargs}", "python runtests.py"),
    ("make {envname}", "make"),
    ("nosetests {toxinidir}/tests", "nosetests /tests"),
    ("python setup.py test {posargs}", "python setup.py test"),
]
for i, (cmd, expected) in enumerate(_tox_non_pytest_subs):
    TOX_CASES.append(pytest.param(
        f"tox_non_pytest_subs_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        expected,
        id=f"tox-non-pytest-subs-{i}",
    ))

# 3g. Command that starts with { → skip, fall through
# When the first_cmd starts with "{", it's skipped (line 314 check)
# and since there's no meaningful command, we fall through to dir check / fallback
_tox_brace_start = [
    ("{posargs}",),
    ("{envpython}",),
    ("{toxinidir}",),
    ("{envdir}",),
    ("{distdir}",),
]
for i, (cmd,) in enumerate(_tox_brace_start):
    TOX_CASES.append(pytest.param(
        f"tox_brace_start_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        PYTEST_TF,
        id=f"tox-brace-start-{i}",
    ))

# 3h. Command where stripping substitutions leaves empty string → fallback
_tox_empty_after_strip = [
    ("{posargs} {envname}",),
    ("{toxinidir}",),
    ("{envpython} {posargs}",),
]
for i, (cmd,) in enumerate(_tox_empty_after_strip):
    TOX_CASES.append(pytest.param(
        f"tox_empty_after_strip_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands = {cmd}
"""},
        PYTEST_TF,
        id=f"tox-empty-after-strip-{i}",
    ))

# 3i. tox.ini with [testenv] but no commands key → regex won't match → fallback
for i in range(10):
    TOX_CASES.append(pytest.param(
        f"tox_no_commands_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
deps = pytest
    coverage
# no commands key here, variation {i}
"""},
        PYTEST_TF,
        id=f"tox-no-commands-{i}",
    ))

# 3j. tox.ini without [testenv] section → regex won't match
for i in range(10):
    TOX_CASES.append(pytest.param(
        f"tox_no_testenv_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv:lint]
commands = flake8
# no [testenv] section, variation {i}
"""},
        PYTEST_TF,
        id=f"tox-no-testenv-{i}",
    ))

# 3k. tox.ini with empty commands
for i in range(5):
    # commands = \n  (just whitespace after =) → regex captures first non-empty
    # Actually the regex `commands\s*=\s*(.+)` requires at least one char after = on same line
    # So empty commands= with nothing after won't match
    TOX_CASES.append(pytest.param(
        f"tox_empty_commands_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
deps = pytest
"""},
        PYTEST_TF,
        id=f"tox-empty-commands-{i}",
    ))

# 3l. tox.ini with commands on next line (regex requires same line)
# The regex `commands\s*=\s*(.+)` requires content on the SAME line as commands=
# So multi-line only commands won't match
for i in range(10):
    TOX_CASES.append(pytest.param(
        f"tox_multiline_no_sameline_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands =
    pytest tests/
"""},
        PYTEST_TF,
        id=f"tox-multiline-no-sameline-{i}",
    ))

# 3m. tox with whitespace between [testenv] and commands
for i in range(10):
    TOX_CASES.append(pytest.param(
        f"tox_whitespace_between_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
deps = pytest
    coverage
basepython = python3.{i % 5 + 8}
commands = pytest tests/ -v
"""},
        PYTEST_TF,
        id=f"tox-whitespace-between-{i}",
    ))

# 3n. Various tox envlist formats
_tox_envlist_variants = [
    "envlist = py38, py39, py310",
    "envlist = py39",
    "envlist =\n    py38\n    py39",
    "envlist = {py38,py39}-{linux,macos}",
    "envlist = py{38,39,310}",
    "envlist = lint, test, docs",
    "envlist = py39-django{32,40}",
    "envlist = py39, lint",
    "envlist = py39-numpy",
    "envlist = py310-pandas",
]
for i, el in enumerate(_tox_envlist_variants):
    TOX_CASES.append(pytest.param(
        f"tox_envlist_{i}",
        {"tox.ini": f"""\
[tox]
{el}

[testenv]
commands = pytest tests/
"""},
        PYTEST_TF,
        id=f"tox-envlist-variant-{i}",
    ))

# 3o. Additional tox pytest patterns with extra spacing
for i in range(15):
    TOX_CASES.append(pytest.param(
        f"tox_extra_spacing_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
commands   =   pytest tests/ -v
"""},
        PYTEST_TF,
        id=f"tox-extra-spacing-{i}",
    ))

# 3p. tox.ini with [testenv] section having commands= on very next line after header
for i in range(10):
    TOX_CASES.append(pytest.param(
        f"tox_immediate_commands_{i}",
        {"tox.ini": f"""\
[testenv]
commands = pytest -v tests/
"""},
        PYTEST_TF,
        id=f"tox-immediate-commands-{i}",
    ))

# 3q. tox with changedir
for i in range(5):
    TOX_CASES.append(pytest.param(
        f"tox_changedir_{i}",
        {"tox.ini": f"""\
[tox]
envlist = py39

[testenv]
changedir = tests
commands = pytest .
"""},
        PYTEST_TF,
        id=f"tox-changedir-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", TOX_CASES)
def test_tox_ini(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 4. tests/ directory exists → "pytest tests/"  (~100)
# ═══════════════════════════════════════════════════════════════════════════

TESTS_DIR_CASES = []

# 4a. Just tests/ dir
for i in range(20):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_only_{i}",
        ["tests"],
        [],
        "pytest tests/",
        id=f"tests-dir-only-{i}",
    ))

# 4b. tests/ dir with test files inside
_test_files = [
    "test_main.py",
    "test_utils.py",
    "test_api.py",
    "test_models.py",
    "test_views.py",
    "test_cli.py",
    "test_db.py",
    "test_auth.py",
    "test_config.py",
    "test_helpers.py",
    "conftest.py",
    "__init__.py",
    "test_integration.py",
    "test_e2e.py",
    "test_smoke.py",
]
for i, tf in enumerate(_test_files):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_with_{tf}_{i}",
        ["tests"],
        [f"tests/{tf}"],
        "pytest tests/",
        id=f"tests-dir-with-{tf.replace('.', '-')}",
    ))

# 4c. tests/ dir with subdirectories
_test_subdirs = [
    "tests/unit",
    "tests/integration",
    "tests/functional",
    "tests/e2e",
    "tests/smoke",
    "tests/regression",
    "tests/perf",
    "tests/api",
    "tests/ui",
    "tests/acceptance",
]
for i, sd in enumerate(_test_subdirs):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_subdir_{i}",
        ["tests", sd],
        [],
        "pytest tests/",
        id=f"tests-dir-subdir-{sd.replace('/', '-')}",
    ))

# 4d. tests/ with other directories that aren't test-related configs
_other_dirs = [
    "src",
    "docs",
    "scripts",
    "build",
    "dist",
    "examples",
    "benchmarks",
    "data",
    "fixtures",
    "assets",
]
for i, od in enumerate(_other_dirs):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_plus_other_{i}",
        ["tests", od],
        [],
        "pytest tests/",
        id=f"tests-dir-plus-{od}",
    ))

# 4e. tests/ with misc files at root (no pyproject, setup.cfg, tox)
_root_files_content = [
    ("README.md", "# My Project"),
    ("setup.py", "from setuptools import setup\nsetup()"),
    ("MANIFEST.in", "include LICENSE"),
    ("Makefile", "test:\n\tpytest tests/"),
    (".gitignore", "*.pyc"),
    ("LICENSE", "MIT License"),
    ("CHANGELOG.md", "# Changelog"),
    ("requirements.txt", "pytest"),
    ("requirements-dev.txt", "pytest\nflake8"),
    (".pre-commit-config.yaml", "repos: []"),
]
for i, (fname, content) in enumerate(_root_files_content):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_with_rootfile_{i}",
        ["tests"],
        [(fname, content)],
        "pytest tests/",
        id=f"tests-dir-with-{fname.replace('.', '-')}",
    ))

# 4f. tests/ with multiple test files
for i in range(15):
    TESTS_DIR_CASES.append(pytest.param(
        f"tests_dir_multi_files_{i}",
        ["tests"],
        [f"tests/test_mod{j}.py" for j in range(i + 1)],
        "pytest tests/",
        id=f"tests-dir-multi-files-{i}",
    ))


@pytest.mark.parametrize("name,dirs,extra_files,expected", TESTS_DIR_CASES)
def test_tests_directory(tmp_path, name, dirs, extra_files, expected):
    for d in dirs:
        _mkdir(tmp_path, d)
    for ef in extra_files:
        if isinstance(ef, tuple):
            _write(tmp_path, ef[0], ef[1])
        else:
            _write(tmp_path, ef, f"# {ef}\n")
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 5. test/ directory exists → "pytest test/"  (~100)
# ═══════════════════════════════════════════════════════════════════════════

TEST_DIR_CASES = []

# 5a. Just test/ dir
for i in range(20):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_only_{i}",
        ["test"],
        [],
        "pytest test/",
        id=f"test-dir-only-{i}",
    ))

# 5b. test/ dir with test files inside
for i, tf in enumerate(_test_files):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_with_{tf}_{i}",
        ["test"],
        [f"test/{tf}"],
        "pytest test/",
        id=f"test-dir-with-{tf.replace('.', '-')}",
    ))

# 5c. test/ dir with subdirectories
_test_dir_subdirs = [
    "test/unit",
    "test/integration",
    "test/functional",
    "test/e2e",
    "test/smoke",
    "test/regression",
    "test/perf",
    "test/api",
    "test/ui",
    "test/acceptance",
]
for i, sd in enumerate(_test_dir_subdirs):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_subdir_{i}",
        ["test", sd],
        [],
        "pytest test/",
        id=f"test-dir-subdir-{sd.replace('/', '-')}",
    ))

# 5d. test/ with other directories
for i, od in enumerate(_other_dirs):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_plus_other_{i}",
        ["test", od],
        [],
        "pytest test/",
        id=f"test-dir-plus-{od}",
    ))

# 5e. test/ with misc root files
for i, (fname, content) in enumerate(_root_files_content):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_with_rootfile_{i}",
        ["test"],
        [(fname, content)],
        "pytest test/",
        id=f"test-dir-with-{fname.replace('.', '-')}",
    ))

# 5f. test/ with multiple test files
for i in range(15):
    TEST_DIR_CASES.append(pytest.param(
        f"test_dir_multi_files_{i}",
        ["test"],
        [f"test/test_mod{j}.py" for j in range(i + 1)],
        "pytest test/",
        id=f"test-dir-multi-files-{i}",
    ))


@pytest.mark.parametrize("name,dirs,extra_files,expected", TEST_DIR_CASES)
def test_test_directory(tmp_path, name, dirs, extra_files, expected):
    for d in dirs:
        _mkdir(tmp_path, d)
    for ef in extra_files:
        if isinstance(ef, tuple):
            _write(tmp_path, ef[0], ef[1])
        else:
            _write(tmp_path, ef, f"# {ef}\n")
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 6. Fallback → "pytest {test_files}"  (~50)
# ═══════════════════════════════════════════════════════════════════════════

FALLBACK_CASES = []

# 6a. Completely empty repo
for i in range(10):
    FALLBACK_CASES.append(pytest.param(
        f"fallback_empty_{i}",
        {},
        [],
        PYTEST_TF,
        id=f"fallback-empty-{i}",
    ))

# 6b. Repo with non-test files only
_non_test_files = [
    ("README.md", "# My Project"),
    ("setup.py", "from setuptools import setup\nsetup()"),
    ("Makefile", "all:\n\techo hello"),
    (".gitignore", "*.pyc\n__pycache__/"),
    ("LICENSE", "MIT License"),
    ("CHANGELOG.md", "# Changes"),
    ("src/__init__.py", ""),
    ("src/main.py", "def main(): pass"),
    ("docs/index.rst", "Welcome"),
    ("requirements.txt", "requests"),
]
for i, (fname, content) in enumerate(_non_test_files):
    FALLBACK_CASES.append(pytest.param(
        f"fallback_with_file_{i}",
        {fname: content},
        [],
        PYTEST_TF,
        id=f"fallback-with-{fname.replace('/', '-').replace('.', '-')}",
    ))

# 6c. pyproject.toml WITHOUT tool.pytest.ini_options
_pyproject_no_pytest = [
    "[project]\nname = 'mypkg'",
    "[build-system]\nrequires = ['setuptools']",
    "[tool.black]\nline-length = 88",
    "[tool.isort]\nprofile = 'black'",
    "[tool.mypy]\nstrict = true",
    "[tool.ruff]\nline-length = 120",
    "[tool.pytest]\n# no ini_options sub-key",
    "[project]\nname = 'mypkg'\nversion = '1.0'",
    "[tool.setuptools]\npackages = ['mypackage']",
    "[tool]\n# bare tool section",
]
for i, content in enumerate(_pyproject_no_pytest):
    FALLBACK_CASES.append(pytest.param(
        f"fallback_pyproject_no_pytest_{i}",
        {"pyproject.toml": content},
        [],
        PYTEST_TF,
        id=f"fallback-pyproject-no-pytest-{i}",
    ))

# 6d. setup.cfg without [tool:pytest]
_cfg_no_pytest = [
    "[metadata]\nname = mypkg",
    "[options]\npackages = find:",
    "[flake8]\nmax-line-length = 120",
    "[isort]\nprofile = black",
    "[mypy]\nstrict = True",
    "[bdist_wheel]\nuniversal = 1",
    "[metadata]\nname = mypkg\n\n[options]\npackages = find:",
    "[options.extras_require]\ndev = pytest",
    "[tool:isort]\nprofile = black",
    "[aliases]\ntest = pytest",
]
for i, content in enumerate(_cfg_no_pytest):
    FALLBACK_CASES.append(pytest.param(
        f"fallback_cfg_no_pytest_{i}",
        {"setup.cfg": content},
        [],
        PYTEST_TF,
        id=f"fallback-cfg-no-pytest-{i}",
    ))


@pytest.mark.parametrize("name,files,dirs,expected", FALLBACK_CASES)
def test_fallback(tmp_path, name, files, dirs, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    for d in dirs:
        _mkdir(tmp_path, d)
    assert detect_test_cmd(tmp_path) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 7. Priority cascade tests  (~150)
# ═══════════════════════════════════════════════════════════════════════════

PRIORITY_CASES = []

# 7a. pyproject wins over setup.cfg
for i in range(20):
    PRIORITY_CASES.append(pytest.param(
        f"priority_pyproject_over_cfg_{i}",
        {
            "pyproject.toml": f"""\
[tool.pytest.ini_options]
addopts = "-v"
# variation {i}
""",
            "setup.cfg": """\
[tool:pytest]
addopts = -v
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-pyproject-over-cfg-{i}",
    ))

# 7b. pyproject wins over tox.ini
for i in range(20):
    PRIORITY_CASES.append(pytest.param(
        f"priority_pyproject_over_tox_{i}",
        {
            "pyproject.toml": f"""\
[tool.pytest.ini_options]
testpaths = ["tests"]
# variation {i}
""",
            "tox.ini": """\
[testenv]
commands = nosetests
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-pyproject-over-tox-{i}",
    ))

# 7c. pyproject wins over tests/ directory
for i in range(15):
    PRIORITY_CASES.append(pytest.param(
        f"priority_pyproject_over_tests_dir_{i}",
        {
            "pyproject.toml": f"""\
[tool.pytest.ini_options]
markers = ["slow"]
# variation {i}
""",
        },
        ["tests"],
        PYTEST_TF,
        id=f"priority-pyproject-over-tests-dir-{i}",
    ))

# 7d. pyproject wins over test/ directory
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_pyproject_over_test_dir_{i}",
        {
            "pyproject.toml": f"""\
[tool.pytest.ini_options]
minversion = "6.0"
# variation {i}
""",
        },
        ["test"],
        PYTEST_TF,
        id=f"priority-pyproject-over-test-dir-{i}",
    ))

# 7e. pyproject wins over everything combined
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_pyproject_over_all_{i}",
        {
            "pyproject.toml": f"""\
[tool.pytest.ini_options]
addopts = "-v"
# variation {i}
""",
            "setup.cfg": """\
[tool:pytest]
addopts = -v
""",
            "tox.ini": """\
[testenv]
commands = nosetests
""",
        },
        ["tests", "test"],
        PYTEST_TF,
        id=f"priority-pyproject-over-all-{i}",
    ))

# 7f. setup.cfg wins over tox.ini (no pyproject pytest config)
for i in range(15):
    PRIORITY_CASES.append(pytest.param(
        f"priority_cfg_over_tox_{i}",
        {
            "setup.cfg": f"""\
[tool:pytest]
addopts = -v
# variation {i}
""",
            "tox.ini": """\
[testenv]
commands = nosetests
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-cfg-over-tox-{i}",
    ))

# 7g. setup.cfg wins over tests/ directory
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_cfg_over_tests_dir_{i}",
        {
            "setup.cfg": f"""\
[tool:pytest]
testpaths = tests
# variation {i}
""",
        },
        ["tests"],
        PYTEST_TF,
        id=f"priority-cfg-over-tests-dir-{i}",
    ))

# 7h. setup.cfg wins over test/ directory
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_cfg_over_test_dir_{i}",
        {
            "setup.cfg": f"""\
[tool:pytest]
markers = slow
# variation {i}
""",
        },
        ["test"],
        PYTEST_TF,
        id=f"priority-cfg-over-test-dir-{i}",
    ))

# 7i. tox.ini wins over tests/ directory
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tox_over_tests_dir_{i}",
        {
            "tox.ini": f"""\
[testenv]
commands = pytest tests/ -v
""",
        },
        ["tests"],
        PYTEST_TF,
        id=f"priority-tox-over-tests-dir-{i}",
    ))

# 7j. tox.ini non-pytest cmd wins over tests/ directory
_tox_non_pytest_priority = [
    ("nosetests tests/", "nosetests tests/"),
    ("python -m unittest discover", "python -m unittest discover"),
    ("trial tests/", "trial tests/"),
    ("make test", "make test"),
    ("green tests/", "green tests/"),
]
for i, (cmd, expected) in enumerate(_tox_non_pytest_priority):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tox_nonpytest_over_tests_{i}",
        {
            "tox.ini": f"""\
[testenv]
commands = {cmd}
""",
        },
        ["tests"],
        expected,
        id=f"priority-tox-nonpytest-over-tests-dir-{i}",
    ))

# 7k. tox.ini wins over test/ directory
for i in range(5):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tox_over_test_dir_{i}",
        {
            "tox.ini": f"""\
[testenv]
commands = pytest -v
""",
        },
        ["test"],
        PYTEST_TF,
        id=f"priority-tox-over-test-dir-{i}",
    ))

# 7l. tests/ wins over test/ (both exist, no config files)
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tests_over_test_{i}",
        {},
        ["tests", "test"],
        "pytest tests/",
        id=f"priority-tests-over-test-{i}",
    ))

# 7m. pyproject WITHOUT ini_options + setup.cfg WITH [tool:pytest] → setup.cfg wins
for i in range(10):
    PRIORITY_CASES.append(pytest.param(
        f"priority_cfg_when_pyproject_no_ini_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mypkg-{i}"
""",
            "setup.cfg": """\
[tool:pytest]
addopts = -v
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-cfg-when-pyproject-no-ini-{i}",
    ))

# 7n. pyproject WITHOUT ini_options + tox with pytest → tox wins
for i in range(5):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tox_when_pyproject_no_ini_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mypkg-{i}"
""",
            "tox.ini": """\
[testenv]
commands = pytest tests/
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-tox-when-pyproject-no-ini-{i}",
    ))

# 7o. setup.cfg WITHOUT [tool:pytest] + tox with pytest → tox
for i in range(5):
    PRIORITY_CASES.append(pytest.param(
        f"priority_tox_when_cfg_no_section_{i}",
        {
            "setup.cfg": f"""\
[metadata]
name = mypkg{i}
""",
            "tox.ini": """\
[testenv]
commands = pytest tests/
""",
        },
        [],
        PYTEST_TF,
        id=f"priority-tox-when-cfg-no-section-{i}",
    ))


@pytest.mark.parametrize("name,files,dirs,expected", PRIORITY_CASES)
def test_priority_cascade(tmp_path, name, files, dirs, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    for d in dirs:
        _mkdir(tmp_path, d)
    assert detect_test_cmd(tmp_path) == expected


EXTRA_PYPROJECT_CASES = []

_extra_ini_keys = [
    'asyncio_mode = "auto"',
    'asyncio_mode = "strict"',
    'timeout = 300',
    'timeout = 60',
    'timeout_method = "signal"',
    'junit_family = "xunit2"',
    'junit_suite_name = "tests"',
    'junit_logging = "all"',
    'doctest_optionflags = "NORMALIZE_WHITESPACE"',
    'faulthandler_timeout = 5',
    'pythonpath = ["src"]',
    'pythonpath = [".", "src"]',
    'tmp_path_retention_policy = "none"',
    'tmp_path_retention_count = 3',
    'empty_parameter_set_mark = "fail_at_collect"',
]
for i, key in enumerate(_extra_ini_keys):
    EXTRA_PYPROJECT_CASES.append(pytest.param(
        f"extra_pyproject_inikey_{i}",
        {"pyproject.toml": f"[tool.pytest.ini_options]\n{key}\n"},
        PYTEST_TF,
        id=f"extra-pyproject-inikey-{i}",
    ))

_extra_pyproject_combos = [
    '[tool.pytest.ini_options]\naddopts = "-v"\ntestpaths = ["tests"]\nmarkers = ["slow"]',
    '[tool.pytest.ini_options]\naddopts = "-ra -q"\ntestpaths = ["tests/unit"]',
    '[tool.pytest.ini_options]\nfilterwarnings = ["error"]\nminversion = "7.0"',
    '[tool.pytest.ini_options]\nlog_cli = true\nlog_cli_level = "DEBUG"',
    '[tool.pytest.ini_options]\npython_files = ["test_*.py"]\npython_classes = ["Test"]',
    '[tool.pytest.ini_options]\nxfail_strict = true\naddopts = "--strict-markers"',
    '[tool.pytest.ini_options]\naddopts = "--cov=src"\ntestpaths = ["tests"]',
    '[tool.pytest.ini_options]\nasyncio_mode = "auto"\naddopts = "-v"',
    '[tool.pytest.ini_options]\naddopts = "--tb=short -q"\nminversion = "6.0"',
    '[tool.pytest.ini_options]\nmarkers = ["slow", "fast"]\ntestpaths = ["tests"]',
    '[tool.pytest.ini_options]\njunit_family = "xunit2"\njunit_suite_name = "ci"',
    '[tool.pytest.ini_options]\naddopts = "--durations=10 -v"\nfilterwarnings = ["error"]',
    '[tool.pytest.ini_options]\naddopts = "-x --maxfail=3"\ntestpaths = ["tests/unit", "tests/integration"]',
    '[tool.pytest.ini_options]\ntimeout = 120\ntimeout_method = "thread"',
    '[tool.pytest.ini_options]\nnorecursedirs = ["build", "dist", ".git"]',
    '[tool.pytest.ini_options]\npythonpath = ["src"]\ntestpaths = ["tests"]',
    '[tool.pytest.ini_options]\nconsole_output_style = "count"\naddopts = "--no-header"',
    '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider"\nfilterwarnings = ["ignore::DeprecationWarning"]',
    '[tool.pytest.ini_options]\ndoctest_optionflags = "ELLIPSIS NORMALIZE_WHITESPACE"',
    '[tool.pytest.ini_options]\naddopts = "--randomly-seed=last"\nmarkers = ["flaky"]',
]
for i, content in enumerate(_extra_pyproject_combos):
    EXTRA_PYPROJECT_CASES.append(pytest.param(
        f"extra_pyproject_combo_{i}",
        {"pyproject.toml": content + "\n"},
        PYTEST_TF,
        id=f"extra-pyproject-combo-{i}",
    ))

for i in range(15):
    EXTRA_PYPROJECT_CASES.append(pytest.param(
        f"extra_pyproject_full_{i}",
        {"pyproject.toml": f"""\
[project]
name = "proj{i}"
version = "{i}.0.0"
requires-python = ">=3.{i % 5 + 8}"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
addopts = "-v --tb=short"
testpaths = ["tests"]
"""},
        PYTEST_TF,
        id=f"extra-pyproject-full-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", EXTRA_PYPROJECT_CASES)
def test_extra_pyproject(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


EXTRA_CFG_CASES = []

_extra_cfg_combos = [
    "[tool:pytest]\naddopts = -v --tb=short\ntestpaths = tests",
    "[tool:pytest]\naddopts = -ra -q\ntestpaths = tests/unit",
    "[tool:pytest]\nfilterwarnings =\n    error\nminversion = 7.0",
    "[tool:pytest]\nlog_cli = true\nlog_cli_level = DEBUG",
    "[tool:pytest]\npython_files = test_*.py check_*.py",
    "[tool:pytest]\nxfail_strict = true\naddopts = --strict-markers",
    "[tool:pytest]\naddopts = --cov=src\ntestpaths = tests",
    "[tool:pytest]\naddopts = -v\nasyncio_mode = auto",
    "[tool:pytest]\nmarkers =\n    slow\n    fast\ntestpaths = tests",
    "[tool:pytest]\njunit_family = xunit2",
    "[tool:pytest]\naddopts = --durations=10 -v\nfilterwarnings =\n    error",
    "[tool:pytest]\naddopts = -x --maxfail=3",
    "[tool:pytest]\ntimeout = 120",
    "[tool:pytest]\nnorecursedirs = build dist .git",
    "[tool:pytest]\nconsole_output_style = count\naddopts = --no-header",
    "[tool:pytest]\naddopts = -p no:cacheprovider",
    "[tool:pytest]\naddopts = --randomly-seed=last\nmarkers = flaky",
    "[tool:pytest]\naddopts = -n auto",
    "[tool:pytest]\naddopts = --dist loadscope",
    "[tool:pytest]\naddopts = --benchmark-disable",
]
for i, content in enumerate(_extra_cfg_combos):
    EXTRA_CFG_CASES.append(pytest.param(
        f"extra_cfg_combo_{i}",
        {"setup.cfg": content + "\n"},
        PYTEST_TF,
        id=f"extra-cfg-combo-{i}",
    ))

for i in range(10):
    EXTRA_CFG_CASES.append(pytest.param(
        f"extra_cfg_full_{i}",
        {"setup.cfg": f"""\
[metadata]
name = proj{i}
version = {i}.0.0

[options]
packages = find:

[tool:pytest]
addopts = -v --tb=short
testpaths = tests
"""},
        PYTEST_TF,
        id=f"extra-cfg-full-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", EXTRA_CFG_CASES)
def test_extra_setup_cfg(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


EXTRA_TOX_CASES = []

_extra_tox_pytest_cmds = [
    "pytest --forked tests/",
    "pytest -p no:randomly",
    "pytest --runxfail",
    "pytest --override-ini=addopts=",
    "pytest tests/ -m 'not slow'",
    "pytest tests/ -m integration",
    "pytest tests/ --ignore=tests/manual",
    "pytest tests/ --rootdir=.",
    "pytest --cache-clear tests/",
    "pytest tests/ --junit-xml=report.xml",
    "pytest --html=report.html tests/",
    "pytest tests/ --log-file=test.log",
    "pytest --stepwise tests/",
    "pytest --stepwise-skip tests/",
    "pytest -p pytest_timeout tests/",
]
for i, cmd in enumerate(_extra_tox_pytest_cmds):
    EXTRA_TOX_CASES.append(pytest.param(
        f"extra_tox_pytest_{i}",
        {"tox.ini": f"[testenv]\ncommands = {cmd}\n"},
        PYTEST_TF,
        id=f"extra-tox-pytest-{i}",
    ))

_extra_tox_non_pytest_cmds = [
    ("unittest discover -s tests", "unittest discover -s tests"),
    ("python -m doctest src/main.py", "python -m doctest src/main.py"),
    ("behave tests/features", "behave tests/features"),
    ("lettuce tests/", "lettuce tests/"),
    ("robot tests/robot", "robot tests/robot"),
    ("tox -e lint", "tox -e lint"),
    ("flake8 src/", "flake8 src/"),
    ("mypy src/", "mypy src/"),
    ("black --check src/", "black --check src/"),
    ("isort --check src/", "isort --check src/"),
    ("bandit -r src/", "bandit -r src/"),
    ("safety check", "safety check"),
    ("vulture src/", "vulture src/"),
    ("pylint src/", "pylint src/"),
    ("pyflakes src/", "pyflakes src/"),
]
for i, (cmd, expected) in enumerate(_extra_tox_non_pytest_cmds):
    EXTRA_TOX_CASES.append(pytest.param(
        f"extra_tox_nonpytest_{i}",
        {"tox.ini": f"[testenv]\ncommands = {cmd}\n"},
        expected,
        id=f"extra-tox-nonpytest-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", EXTRA_TOX_CASES)
def test_extra_tox(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    assert detect_test_cmd(tmp_path) == expected


EXTRA_DIR_CASES = []

for i in range(10):
    EXTRA_DIR_CASES.append(pytest.param(
        f"extra_tests_nested_{i}",
        ["tests", f"tests/sub{i}"],
        [f"tests/sub{i}/test_mod.py"],
        "pytest tests/",
        id=f"extra-tests-nested-{i}",
    ))

for i in range(10):
    EXTRA_DIR_CASES.append(pytest.param(
        f"extra_test_nested_{i}",
        ["test", f"test/sub{i}"],
        [f"test/sub{i}/test_mod.py"],
        "pytest test/",
        id=f"extra-test-nested-{i}",
    ))


@pytest.mark.parametrize("name,dirs,extra_files,expected", EXTRA_DIR_CASES)
def test_extra_directories(tmp_path, name, dirs, extra_files, expected):
    for d in dirs:
        _mkdir(tmp_path, d)
    for ef in extra_files:
        if isinstance(ef, tuple):
            _write(tmp_path, ef[0], ef[1])
        else:
            _write(tmp_path, ef, f"# {ef}\n")
    assert detect_test_cmd(tmp_path) == expected


EXTRA_PRIORITY_CASES = []

for i in range(10):
    EXTRA_PRIORITY_CASES.append(pytest.param(
        f"extra_all_configs_pyproject_wins_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "p{i}"

[tool.pytest.ini_options]
addopts = "-v"
""",
            "setup.cfg": """\
[metadata]
name = mypkg

[tool:pytest]
addopts = -v
""",
            "tox.ini": """\
[testenv]
commands = nosetests tests/
""",
        },
        ["tests", "test"],
        PYTEST_TF,
        id=f"extra-all-configs-pyproject-wins-{i}",
    ))

for i in range(10):
    EXTRA_PRIORITY_CASES.append(pytest.param(
        f"extra_cfg_tox_dirs_cfg_wins_{i}",
        {
            "setup.cfg": f"""\
[tool:pytest]
addopts = -v
""",
            "tox.ini": """\
[testenv]
commands = nosetests tests/
""",
        },
        ["tests", "test"],
        PYTEST_TF,
        id=f"extra-cfg-tox-dirs-cfg-wins-{i}",
    ))

for i in range(5):
    EXTRA_PRIORITY_CASES.append(pytest.param(
        f"extra_tox_both_dirs_{i}",
        {
            "tox.ini": """\
[testenv]
commands = nosetests tests/
""",
        },
        ["tests", "test"],
        "nosetests tests/",
        id=f"extra-tox-both-dirs-{i}",
    ))


@pytest.mark.parametrize("name,files,dirs,expected", EXTRA_PRIORITY_CASES)
def test_extra_priority(tmp_path, name, files, dirs, expected):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    for d in dirs:
        _mkdir(tmp_path, d)
    assert detect_test_cmd(tmp_path) == expected
