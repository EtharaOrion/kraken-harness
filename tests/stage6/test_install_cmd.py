import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_install_cmd

MESON_CMD = "pip install --no-build-isolation -e ."
STD_CMD = "pip install -e ."


def _write_pyproject(tmp_path, requires_list):
    lines = ['[build-system]\nrequires = [\n']
    for r in requires_list:
        lines.append(f'    "{r}",\n')
    lines.append(']\n')
    (tmp_path / "pyproject.toml").write_text("".join(lines))


def _write_pyproject_no_bs(tmp_path, extra=""):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "foo"\n{extra}')


def _write_setup_py(tmp_path, content="from setuptools import setup\nsetup()"):
    (tmp_path / "setup.py").write_text(content)


def _write_setup_cfg(tmp_path, content="[metadata]\nname = foo\n"):
    (tmp_path / "setup.cfg").write_text(content)


# ============================================================
# 1. Meson / scikit-build → --no-build-isolation  (~200)
# ============================================================

_meson_cases = []

# --- meson-python variants ---
_mp_bases = [
    "meson-python",
    "Meson-Python",
    "MESON-PYTHON",
    "meson-python>=0.1",
    "meson-python>=0.12.0",
    "meson-python>=0.13",
    "meson-python>=1.0",
    "meson-python>=0.1,<2",
    "meson-python~=0.12",
    "meson-python==0.13.1",
    "meson-python!=0.10",
    "Meson-Python>=0.12.0",
    "MESON-PYTHON>=1.0.0",
    "meson-python[extra]",
    "meson-python ; python_version >= '3.8'",
]

for i, mp in enumerate(_mp_bases):
    _meson_cases.append(pytest.param([mp], MESON_CMD, id=f"meson_python_alone_{i}"))

for i, mp in enumerate(_mp_bases):
    _meson_cases.append(pytest.param([mp, "numpy"], MESON_CMD, id=f"meson_python_with_numpy_{i}"))

for i, mp in enumerate(_mp_bases):
    _meson_cases.append(pytest.param(["cython", mp], MESON_CMD, id=f"meson_python_after_cython_{i}"))

for i, mp in enumerate(_mp_bases):
    _meson_cases.append(pytest.param(["numpy", "cython>=0.29", mp, "wheel"], MESON_CMD, id=f"meson_python_in_multi_{i}"))

# --- mesonpy variants ---
_mpy_bases = [
    "mesonpy",
    "Mesonpy",
    "MESONPY",
    "mesonpy>=0.1",
    "mesonpy>=0.12.0",
    "mesonpy>=1.0",
    "mesonpy~=0.5",
    "mesonpy==0.8",
    "Mesonpy>=0.12",
    "MESONPY>=1.0.0",
]

for i, mp in enumerate(_mpy_bases):
    _meson_cases.append(pytest.param([mp], MESON_CMD, id=f"mesonpy_alone_{i}"))

for i, mp in enumerate(_mpy_bases):
    _meson_cases.append(pytest.param([mp, "setuptools"], MESON_CMD, id=f"mesonpy_with_setuptools_{i}"))

for i, mp in enumerate(_mpy_bases):
    _meson_cases.append(pytest.param(["wheel", mp], MESON_CMD, id=f"mesonpy_after_wheel_{i}"))

# --- scikit-build variants ---
_sb_bases = [
    "scikit-build",
    "Scikit-Build",
    "SCIKIT-BUILD",
    "scikit-build>=0.1",
    "scikit-build>=0.15",
    "scikit-build>=0.17",
    "scikit-build~=0.15",
    "scikit-build==0.17.1",
    "scikit-build!=0.10",
    "Scikit-Build>=0.15.0",
    "SCIKIT-BUILD>=1.0.0",
    "scikit-build-core",
    "scikit-build-core>=0.1",
    "Scikit-Build-Core>=0.5",
    "SCIKIT-BUILD-CORE>=1.0",
    "scikit-build-core~=0.5",
    "scikit-build-core==0.8.0",
    "scikit-build-core[pyproject]",
    "scikit-build-core ; python_version >= '3.8'",
    "scikit-build-core>=0.5,<1.0",
]

for i, sb in enumerate(_sb_bases):
    _meson_cases.append(pytest.param([sb], MESON_CMD, id=f"scikit_build_alone_{i}"))

for i, sb in enumerate(_sb_bases):
    _meson_cases.append(pytest.param([sb, "cmake", "ninja"], MESON_CMD, id=f"scikit_build_with_cmake_{i}"))

for i, sb in enumerate(_sb_bases):
    _meson_cases.append(pytest.param(["numpy>=1.20", sb], MESON_CMD, id=f"scikit_build_after_numpy_{i}"))

for i, sb in enumerate(_sb_bases[:10]):
    _meson_cases.append(pytest.param(["cython", "numpy", sb, "wheel", "packaging"], MESON_CMD, id=f"scikit_build_in_big_list_{i}"))


@pytest.mark.parametrize("requires,expected", _meson_cases)
def test_meson_scikit_build(tmp_path, requires, expected):
    _write_pyproject(tmp_path, requires)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 2. Standard backends → "pip install -e ."  (~300)
# ============================================================

_std_cases = []

_setuptools_variants = [
    "setuptools",
    "Setuptools",
    "SETUPTOOLS",
    "setuptools>=40",
    "setuptools>=42",
    "setuptools>=45",
    "setuptools>=60",
    "setuptools>=61",
    "setuptools>=64",
    "setuptools>=67",
    "setuptools>=68",
    "setuptools>=69",
    "setuptools>=70",
    "setuptools>=40.8",
    "setuptools>=42.0",
    "setuptools>=45.0",
    "setuptools>=61.0",
    "setuptools>=64.0.0",
    "setuptools~=68.0",
    "setuptools==69.0.0",
    "setuptools!=60.0",
    "Setuptools>=61.0",
    "SETUPTOOLS>=70.0",
    "setuptools[testing]",
    "setuptools ; python_version >= '3.8'",
    "setuptools>=40,<70",
]

_flit_core_variants = [
    "flit-core",
    "flit_core",
    "Flit-Core",
    "Flit_Core",
    "FLIT-CORE",
    "FLIT_CORE",
    "flit-core>=3",
    "flit_core>=3",
    "flit-core>=3.2",
    "flit_core>=3.2",
    "flit-core>=3.4",
    "flit_core>=3.4",
    "flit-core~=3.2",
    "flit_core~=3.2",
    "flit-core==3.9.0",
    "flit_core==3.9.0",
    "Flit-Core>=3.2",
    "Flit_Core>=3.2",
    "FLIT-CORE>=3.0",
    "FLIT_CORE>=3.0",
]

_hatchling_variants = [
    "hatchling",
    "Hatchling",
    "HATCHLING",
    "hatchling>=1.0",
    "hatchling>=1.8",
    "hatchling>=1.11",
    "hatchling>=1.13",
    "hatchling>=1.18",
    "hatchling~=1.11",
    "hatchling==1.18.0",
    "Hatchling>=1.8",
    "HATCHLING>=1.0",
    "hatchling ; python_version >= '3.7'",
    "hatchling>=1.0,<2",
]

_poetry_core_variants = [
    "poetry-core",
    "poetry_core",
    "Poetry-Core",
    "Poetry_Core",
    "POETRY-CORE",
    "POETRY_CORE",
    "poetry-core>=1.0",
    "poetry_core>=1.0",
    "poetry-core>=1.0.0",
    "poetry_core>=1.0.0",
    "poetry-core~=1.0",
    "poetry_core~=1.0",
    "poetry-core==1.5.0",
    "poetry_core==1.5.0",
    "Poetry-Core>=1.0",
    "Poetry_Core>=1.0",
]

_pdm_variants = [
    "pdm-backend",
    "Pdm-Backend",
    "PDM-BACKEND",
    "pdm-backend>=2.0",
    "pdm-backend>=2.1",
    "pdm-backend~=2.0",
    "pdm-backend==2.1.0",
    "Pdm-Backend>=2.0",
    "PDM-BACKEND>=2.0",
    "pdm-pep517",
    "Pdm-Pep517",
    "PDM-PEP517",
    "pdm-pep517>=1.0",
    "pdm-pep517>=0.12",
    "pdm-pep517~=1.0",
    "pdm-pep517==1.0.0",
    "Pdm-Pep517>=1.0",
    "PDM-PEP517>=1.0",
]

# alone
for i, v in enumerate(_setuptools_variants):
    _std_cases.append(pytest.param([v], STD_CMD, id=f"setuptools_alone_{i}"))
for i, v in enumerate(_flit_core_variants):
    _std_cases.append(pytest.param([v], STD_CMD, id=f"flit_core_alone_{i}"))
for i, v in enumerate(_hatchling_variants):
    _std_cases.append(pytest.param([v], STD_CMD, id=f"hatchling_alone_{i}"))
for i, v in enumerate(_poetry_core_variants):
    _std_cases.append(pytest.param([v], STD_CMD, id=f"poetry_core_alone_{i}"))
for i, v in enumerate(_pdm_variants):
    _std_cases.append(pytest.param([v], STD_CMD, id=f"pdm_alone_{i}"))

# with wheel
for i, v in enumerate(_setuptools_variants):
    _std_cases.append(pytest.param([v, "wheel"], STD_CMD, id=f"setuptools_wheel_{i}"))
for i, v in enumerate(_flit_core_variants[:10]):
    _std_cases.append(pytest.param([v, "wheel"], STD_CMD, id=f"flit_core_wheel_{i}"))
for i, v in enumerate(_hatchling_variants[:7]):
    _std_cases.append(pytest.param([v, "wheel"], STD_CMD, id=f"hatchling_wheel_{i}"))
for i, v in enumerate(_poetry_core_variants[:8]):
    _std_cases.append(pytest.param([v, "wheel"], STD_CMD, id=f"poetry_core_wheel_{i}"))
for i, v in enumerate(_pdm_variants[:9]):
    _std_cases.append(pytest.param([v, "wheel"], STD_CMD, id=f"pdm_wheel_{i}"))

# with setuptools-scm
for i, v in enumerate(_setuptools_variants[:13]):
    _std_cases.append(pytest.param([v, "setuptools-scm"], STD_CMD, id=f"setuptools_scm_{i}"))

# multi deps
for i, v in enumerate(_setuptools_variants[:13]):
    _std_cases.append(pytest.param([v, "wheel", "setuptools-scm>=6.0", "cython"], STD_CMD, id=f"setuptools_multi_{i}"))

# flit + extras
for i, v in enumerate(_flit_core_variants[:10]):
    _std_cases.append(pytest.param(["wheel", v, "tomli"], STD_CMD, id=f"flit_core_multi_{i}"))


@pytest.mark.parametrize("requires,expected", _std_cases)
def test_standard_backends(tmp_path, requires, expected):
    _write_pyproject(tmp_path, requires)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 3. Unknown backend with requires → "pip install -e ."  (~100)
# ============================================================

_unknown_backends = [
    "my-custom-backend",
    "acme-builder",
    "foo-build",
    "bar-backend",
    "baz-pep517",
    "custom-builder>=1.0",
    "my-build-system>=2.0",
    "experimental-backend",
    "nuitka",
    "maturin",
    "Maturin",
    "MATURIN",
    "maturin>=1.0",
    "maturin>=0.14",
    "maturin~=1.0",
    "maturin==1.4.0",
    "enscons",
    "Enscons",
    "enscons>=0.26",
    "jupyter-packaging",
    "jupyter_packaging",
    "jupyter-packaging>=0.10",
    "whey",
    "Whey",
    "whey>=0.0.20",
    "trampolim",
    "Trampolim",
    "trampolim>=0.1",
    "sipbuild",
    "Sipbuild",
    "sipbuild>=6.0",
    "cmake",
    "ninja",
    "pybind11",
    "pybind11>=2.10",
    "nanobind",
    "cython",
    "Cython",
    "cython>=0.29",
    "cffi",
    "CFFI",
    "cffi>=1.0",
    "swig",
    "SWIG",
]

_unknown_cases = []

for i, ub in enumerate(_unknown_backends):
    _unknown_cases.append(pytest.param([ub], STD_CMD, id=f"unknown_alone_{i}"))

for i, ub in enumerate(_unknown_backends[:22]):
    _unknown_cases.append(pytest.param([ub, "wheel"], STD_CMD, id=f"unknown_with_wheel_{i}"))

for i, ub in enumerate(_unknown_backends[:22]):
    _unknown_cases.append(pytest.param(["wheel", ub, "packaging"], STD_CMD, id=f"unknown_multi_{i}"))


@pytest.mark.parametrize("requires,expected", _unknown_cases)
def test_unknown_backend_with_requires(tmp_path, requires, expected):
    _write_pyproject(tmp_path, requires)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 4. No pyproject but setup.py → "pip install -e ."  (~150)
# ============================================================

_setup_py_contents = [
    "from setuptools import setup\nsetup()",
    "from setuptools import setup\nsetup(name='foo')",
    "from setuptools import setup\nsetup(name='foo', version='1.0')",
    "from setuptools import setup, find_packages\nsetup(name='foo', packages=find_packages())",
    "from distutils.core import setup\nsetup()",
    "from distutils.core import setup\nsetup(name='bar')",
    "import setuptools\nsetuptools.setup()",
    "import setuptools\nsetuptools.setup(name='baz')",
    "from numpy.distutils.core import setup\nsetup()",
    "from numpy.distutils.misc_util import Configuration\n",
    "#!/usr/bin/env python\nfrom setuptools import setup\nsetup()",
    "#!/usr/bin/env python3\nfrom setuptools import setup\nsetup()",
    "# setup file\nfrom setuptools import setup\nsetup()",
    "",
    " ",
    "\n",
    "pass",
    "# empty setup",
    "print('hello')",
    "import sys",
    "from setuptools import setup\nsetup(\n    name='foo',\n    version='0.1',\n    install_requires=['numpy'],\n)",
    "from setuptools import setup\nsetup(\n    name='bar',\n    packages=['bar'],\n    python_requires='>=3.6',\n)",
    "from setuptools import setup\nimport os\nsetup(name='pkg')",
    "from setuptools import setup, Extension\next = Extension('mod', sources=['mod.c'])\nsetup(ext_modules=[ext])",
    "from Cython.Build import cythonize\nfrom setuptools import setup\nsetup(ext_modules=cythonize('*.pyx'))",
]

_setup_py_cases = []

for i, content in enumerate(_setup_py_contents):
    _setup_py_cases.append(pytest.param(content, STD_CMD, id=f"setup_py_content_{i}"))

# Various names/patterns but same thing — setup.py exists
_extra_setup_py = []
for idx in range(125):
    c = f"# auto-generated setup {idx}\nfrom setuptools import setup\nsetup(name='pkg{idx}')"
    _extra_setup_py.append(c)

for i, content in enumerate(_extra_setup_py):
    _setup_py_cases.append(pytest.param(content, STD_CMD, id=f"setup_py_generated_{i}"))


@pytest.mark.parametrize("content,expected", _setup_py_cases)
def test_setup_py_exists(tmp_path, content, expected):
    _write_setup_py(tmp_path, content)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 5. setup.cfg with [metadata] → "pip install -e ."  (~150)
# ============================================================

_setup_cfg_valid = [
    "[metadata]\nname = foo\n",
    "[metadata]\nname = foo\nversion = 1.0\n",
    "[metadata]\nname = foo\nversion = 1.0\nauthor = Test\n",
    "[metadata]\nname = foo\nversion = 1.0\nauthor = Test\nemail = test@test.com\n",
    "[metadata]\nname = foo\nversion = 1.0\ndescription = A package\n",
    "[metadata]\nname = foo\nversion = 1.0\nlong_description = file: README.md\n",
    "[metadata]\nname = foo\nurl = https://example.com\n",
    "[metadata]\nname = foo\nlicense = MIT\n",
    "[metadata]\nname = foo\nclassifiers =\n    Programming Language :: Python :: 3\n",
    "[metadata]\nname = foo\nplatform = any\n",
    "[metadata]\nname = foo\n\n[options]\npackages = find:\n",
    "[metadata]\nname = foo\n\n[options]\ninstall_requires =\n    numpy\n",
    "[metadata]\nname = foo\n\n[options]\npython_requires = >=3.8\n",
    "[metadata]\nname = foo\n\n[options.extras_require]\ndev = pytest\n",
    "[metadata]\nname = foo\n\n[options.packages.find]\nwhere = src\n",
    "[metadata]\nname = foo\nversion = attr: pkg.__version__\n",
]

_setup_cfg_no_metadata = [
    "[options]\npackages = find:\n",
    "[options]\ninstall_requires = numpy\n",
    "[tool:pytest]\naddopts = -v\n",
    "[bdist_wheel]\nuniversal = 1\n",
    "[flake8]\nmax-line-length = 120\n",
    "",
    " ",
    "\n",
    "# just a comment\n",
    "[options]\n",
    "[egg_info]\ntag_build = dev\n",
]

_setup_cfg_cases_valid = []
_setup_cfg_cases_no_meta = []

for i, cfg in enumerate(_setup_cfg_valid):
    _setup_cfg_cases_valid.append(pytest.param(cfg, STD_CMD, id=f"cfg_valid_{i}"))

# Generate more valid metadata variants
for idx in range(67):
    c = f"[metadata]\nname = pkg{idx}\nversion = {idx}.0\n"
    _setup_cfg_cases_valid.append(pytest.param(c, STD_CMD, id=f"cfg_valid_gen_{idx}"))

for idx in range(67):
    c = f"[metadata]\nname = lib{idx}\nversion = 0.{idx}\nauthor = Author{idx}\n"
    _setup_cfg_cases_valid.append(pytest.param(c, STD_CMD, id=f"cfg_valid_gen_extra_{idx}"))


@pytest.mark.parametrize("content,expected", _setup_cfg_cases_valid)
def test_setup_cfg_with_metadata(tmp_path, content, expected):
    _write_setup_cfg(tmp_path, content)
    assert detect_install_cmd(tmp_path) == expected


for i, cfg in enumerate(_setup_cfg_no_metadata):
    _setup_cfg_cases_no_meta.append(pytest.param(cfg, STD_CMD, id=f"cfg_no_meta_{i}"))

for idx in range(50):
    c = f"[options]\npackage_dir_{idx} = src\n"
    _setup_cfg_cases_no_meta.append(pytest.param(c, STD_CMD, id=f"cfg_no_meta_gen_{idx}"))


@pytest.mark.parametrize("content,expected", _setup_cfg_cases_no_meta)
def test_setup_cfg_no_metadata_fallback(tmp_path, content, expected):
    _write_setup_cfg(tmp_path, content)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 6. Fallback → "pip install -e ."  (~100)
# ============================================================

_fallback_cases = []

# Empty repo
_fallback_cases.append(pytest.param([], STD_CMD, id="empty_repo"))

# Only irrelevant files
_irrelevant_files = [
    "README.md", "README.rst", "README.txt", "README",
    "LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING",
    "CHANGELOG.md", "CHANGELOG.rst", "HISTORY.md",
    "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".gitignore", ".gitattributes",
    "tox.ini", "mypy.ini", ".flake8",
    "requirements.txt", "requirements-dev.txt",
    "constraints.txt",
    ".pre-commit-config.yaml",
    ".editorconfig",
    ".pylintrc",
    "MANIFEST.in",
    "pytest.ini",
    "noxfile.py",
    "tasks.py",
    "conftest.py",
    ".coveragerc",
    ".isort.cfg",
    "pyproject_other.toml",
    "package.json",
    "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "build.gradle",
    "pom.xml",
    "CMakeLists.txt",
    "meson.build",
]

for i, fname in enumerate(_irrelevant_files):
    _fallback_cases.append(pytest.param([fname], STD_CMD, id=f"irrelevant_{i}"))

# Combinations of irrelevant files
for i in range(0, len(_irrelevant_files) - 2, 2):
    combo = [_irrelevant_files[i], _irrelevant_files[i + 1]]
    _fallback_cases.append(pytest.param(combo, STD_CMD, id=f"irrelevant_combo_{i}"))

# Only source files
for idx in range(20):
    _fallback_cases.append(pytest.param([f"module{idx}.py"], STD_CMD, id=f"only_py_{idx}"))

# Only data files
for idx in range(10):
    _fallback_cases.append(pytest.param([f"data{idx}.csv"], STD_CMD, id=f"only_data_{idx}"))


@pytest.mark.parametrize("files,expected", _fallback_cases)
def test_fallback(tmp_path, files, expected):
    for f in files:
        (tmp_path / f).write_text(f"# {f}")
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 7. Priority tests  (~200)
# ============================================================

# -- 7a: pyproject meson + setup.py → meson wins --

_priority_meson_setup_py = []

_meson_reqs = [
    ["meson-python"],
    ["meson-python>=0.12"],
    ["mesonpy"],
    ["mesonpy>=0.5"],
    ["scikit-build"],
    ["scikit-build>=0.15"],
    ["scikit-build-core"],
    ["scikit-build-core>=0.5"],
    ["meson-python", "numpy"],
    ["meson-python", "cython"],
    ["mesonpy", "wheel"],
    ["scikit-build", "cmake", "ninja"],
    ["scikit-build-core", "pybind11"],
    ["meson-python>=0.13", "numpy>=1.20", "cython"],
    ["scikit-build>=0.17", "cmake>=3.15", "ninja"],
    ["MESON-PYTHON"],
    ["Mesonpy"],
    ["SCIKIT-BUILD"],
    ["Scikit-Build-Core>=0.5"],
    ["meson-python>=0.1,<2"],
]

_setup_py_for_priority = [
    "from setuptools import setup\nsetup()",
    "from setuptools import setup\nsetup(name='x')",
    "from distutils.core import setup\nsetup()",
    "",
    "pass",
]

for i, reqs in enumerate(_meson_reqs):
    for j, spy in enumerate(_setup_py_for_priority):
        _priority_meson_setup_py.append(
            pytest.param(reqs, spy, MESON_CMD, id=f"pri_meson_sp_{i}_{j}")
        )


@pytest.mark.parametrize("requires,spy_content,expected", _priority_meson_setup_py)
def test_priority_meson_over_setup_py(tmp_path, requires, spy_content, expected):
    _write_pyproject(tmp_path, requires)
    _write_setup_py(tmp_path, spy_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7b: pyproject std + setup.py → pyproject std wins --

_priority_std_setup_py = []

_std_reqs_for_priority = [
    ["setuptools"],
    ["setuptools>=61"],
    ["flit-core"],
    ["flit_core>=3.2"],
    ["hatchling"],
    ["hatchling>=1.8"],
    ["poetry-core"],
    ["poetry_core>=1.0"],
    ["pdm-backend"],
    ["pdm-pep517"],
    ["setuptools", "wheel"],
    ["setuptools>=61", "setuptools-scm"],
    ["flit-core>=3.4", "wheel"],
    ["hatchling>=1.11", "hatch-vcs"],
    ["poetry-core>=1.0.0", "wheel"],
]

for i, reqs in enumerate(_std_reqs_for_priority):
    for j, spy in enumerate(_setup_py_for_priority):
        _priority_std_setup_py.append(
            pytest.param(reqs, spy, STD_CMD, id=f"pri_std_sp_{i}_{j}")
        )


@pytest.mark.parametrize("requires,spy_content,expected", _priority_std_setup_py)
def test_priority_std_over_setup_py(tmp_path, requires, spy_content, expected):
    _write_pyproject(tmp_path, requires)
    _write_setup_py(tmp_path, spy_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7c: pyproject meson + setup.cfg → meson wins --

_priority_meson_cfg = []

_cfg_contents_for_priority = [
    "[metadata]\nname = foo\n",
    "[metadata]\nname = bar\nversion = 1.0\n",
    "[options]\npackages = find:\n",
]

for i, reqs in enumerate(_meson_reqs[:10]):
    for j, cfg in enumerate(_cfg_contents_for_priority):
        _priority_meson_cfg.append(
            pytest.param(reqs, cfg, MESON_CMD, id=f"pri_meson_cfg_{i}_{j}")
        )


@pytest.mark.parametrize("requires,cfg_content,expected", _priority_meson_cfg)
def test_priority_meson_over_cfg(tmp_path, requires, cfg_content, expected):
    _write_pyproject(tmp_path, requires)
    _write_setup_cfg(tmp_path, cfg_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7d: pyproject std + setup.cfg → pyproject wins --

_priority_std_cfg = []

for i, reqs in enumerate(_std_reqs_for_priority):
    for j, cfg in enumerate(_cfg_contents_for_priority):
        _priority_std_cfg.append(
            pytest.param(reqs, cfg, STD_CMD, id=f"pri_std_cfg_{i}_{j}")
        )


@pytest.mark.parametrize("requires,cfg_content,expected", _priority_std_cfg)
def test_priority_std_over_cfg(tmp_path, requires, cfg_content, expected):
    _write_pyproject(tmp_path, requires)
    _write_setup_cfg(tmp_path, cfg_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7e: setup.py + setup.cfg → setup.py wins --

_priority_sp_cfg = []

for i, spy in enumerate(_setup_py_for_priority):
    for j, cfg in enumerate(_cfg_contents_for_priority):
        _priority_sp_cfg.append(
            pytest.param(spy, cfg, STD_CMD, id=f"pri_sp_cfg_{i}_{j}")
        )


@pytest.mark.parametrize("spy_content,cfg_content,expected", _priority_sp_cfg)
def test_priority_setup_py_over_cfg(tmp_path, spy_content, cfg_content, expected):
    _write_setup_py(tmp_path, spy_content)
    _write_setup_cfg(tmp_path, cfg_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7f: pyproject no build-system + setup.py → setup.py wins --

_priority_no_bs_sp = []

_no_bs_extras = [
    "",
    'version = "1.0"',
    'description = "A project"',
]

for i, extra in enumerate(_no_bs_extras):
    for j, spy in enumerate(_setup_py_for_priority):
        _priority_no_bs_sp.append(
            pytest.param(extra, spy, STD_CMD, id=f"pri_nobs_sp_{i}_{j}")
        )


@pytest.mark.parametrize("extra,spy_content,expected", _priority_no_bs_sp)
def test_priority_no_buildsystem_setup_py(tmp_path, extra, spy_content, expected):
    _write_pyproject_no_bs(tmp_path, extra)
    _write_setup_py(tmp_path, spy_content)
    assert detect_install_cmd(tmp_path) == expected


# -- 7g: all three: pyproject meson + setup.py + setup.cfg --

_priority_all_meson = []

for i, reqs in enumerate(_meson_reqs[:7]):
    for j, spy in enumerate(_setup_py_for_priority[:3]):
        for k, cfg in enumerate(_cfg_contents_for_priority):
            _priority_all_meson.append(
                pytest.param(reqs, spy, cfg, MESON_CMD, id=f"pri_all_meson_{i}_{j}_{k}")
            )


@pytest.mark.parametrize("requires,spy_content,cfg_content,expected", _priority_all_meson)
def test_priority_all_three_meson(tmp_path, requires, spy_content, cfg_content, expected):
    _write_pyproject(tmp_path, requires)
    _write_setup_py(tmp_path, spy_content)
    _write_setup_cfg(tmp_path, cfg_content)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 8. Edge cases (pyproject exists but no build-system)
# ============================================================

_no_bs_cases = []

_no_bs_pyprojects = [
    '[project]\nname = "foo"\n',
    '[project]\nname = "foo"\nversion = "1.0"\n',
    '[project]\nname = "foo"\nrequires-python = ">=3.8"\n',
    '[tool.pytest.ini_options]\naddopts = "-v"\n',
    '[tool.black]\nline-length = 88\n',
    '[tool.isort]\nprofile = "black"\n',
    '[tool.mypy]\nstrict = true\n',
    '',
    '\n',
    '# empty toml\n',
]

for i, content in enumerate(_no_bs_pyprojects):
    _no_bs_cases.append(pytest.param(content, STD_CMD, id=f"no_bs_pyproject_{i}"))


@pytest.mark.parametrize("content,expected", _no_bs_cases)
def test_pyproject_no_build_system_fallback(tmp_path, content, expected):
    (tmp_path / "pyproject.toml").write_text(content)
    assert detect_install_cmd(tmp_path) == expected


# ============================================================
# 9. Empty requires list edge
# ============================================================

_empty_req_cases = []

_empty_req_pyprojects = [
    '[build-system]\nrequires = []\n',
    '[build-system]\nrequires = []\nbuild-backend = "setuptools.build_meta"\n',
    '[build-system]\nrequires = []\nbuild-backend = "flit_core.buildapi"\n',
]

for i, content in enumerate(_empty_req_pyprojects):
    _empty_req_cases.append(pytest.param(content, STD_CMD, id=f"empty_requires_{i}"))


@pytest.mark.parametrize("content,expected", _empty_req_cases)
def test_empty_requires_fallback(tmp_path, content, expected):
    (tmp_path / "pyproject.toml").write_text(content)
    assert detect_install_cmd(tmp_path) == expected
