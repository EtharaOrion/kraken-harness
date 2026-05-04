"""Tests for detect_pre_install() — ~1200 parametrized test cases.

Covers: C extensions in setup.py, meson.build, Fortran files,
BLAS/LAPACK detection, combinations, negatives, and ordering.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_pre_install

BUILD = "apt-get install -y build-essential"
MESON = "apt-get install -y meson ninja-build"
GFORTRAN = "apt-get install -y gfortran"
OPENBLAS = "apt-get install -y libopenblas-dev"


def _setup_repo(tmp_path, *, setup_py=None, pyproject=None, meson=None,
                files=None):
    if setup_py is not None:
        (tmp_path / "setup.py").write_text(setup_py, encoding="utf-8")
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if meson is not None:
        (tmp_path / "meson.build").write_text(meson, encoding="utf-8")
    for relpath, content in (files or []):
        p = tmp_path / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# =====================================================================
# Category 1: C extensions in setup.py (~200 tests)
# =====================================================================

_C_EXT_KEYWORD_CASES = []

# --- ext_modules variations ---
_ext_modules_snippets = [
    ("ext_modules_basic", "ext_modules = [Extension('foo', ['foo.c'])]"),
    ("ext_modules_empty_list", "ext_modules=[]"),
    ("ext_modules_spaced", "ext_modules  =  [Extension('bar', sources=['bar.c'])]"),
    ("ext_modules_multiline", "setup(\n    ext_modules=[\n        Extension('x', ['x.c']),\n    ],\n)"),
    ("ext_modules_in_variable", "my_ext_modules = [Extension('y', ['y.c'])]"),
    ("ext_modules_inline", "setup(ext_modules=cythonize(extensions))"),
    ("ext_modules_commented", "# ext_modules = [Extension('z', ['z.c'])]"),
    ("ext_modules_in_string", 'desc = "has ext_modules keyword"'),
    ("ext_modules_in_docstring", '"""ext_modules config."""\next_modules=[]'),
    ("ext_modules_tab_indent", "\text_modules = [Extension('w', ['w.c'])]"),
    ("ext_modules_deep_indent", "        ext_modules = extensions"),
    ("ext_modules_concat", "all_ext_modules = a + b"),
    ("ext_modules_if_block", "if True:\n    ext_modules = []"),
    ("ext_modules_dict", "cfg = {'ext_modules': exts}"),
    ("ext_modules_kwarg", "setup(**{'ext_modules': exts})"),
    ("ext_modules_late", "# lots of code\n" * 50 + "ext_modules = []"),
    ("ext_modules_early", "ext_modules = []\n" + "# lots of code\n" * 50),
    ("ext_modules_middle", "# code\n" * 25 + "ext_modules = []\n" + "# code\n" * 25),
    ("ext_modules_with_cython", "ext_modules = cythonize(extensions)"),
    ("ext_modules_complex", "ext_modules=cythonize([Extension('a',['a.pyx']),Extension('b',['b.pyx'])])"),
    ("ext_modules_numpy", "from numpy.distutils.core import Extension\next_modules=[Extension('f',['f.f90'])]"),
    ("ext_modules_setuptools", "from setuptools import Extension\next_modules = [Extension('m', ['m.c'])]"),
    ("ext_modules_conditional", "ext_modules = exts if HAS_CYTHON else []"),
    ("ext_modules_none", "ext_modules = None  # still matches keyword"),
    ("ext_modules_assigned_fn", "ext_modules = get_extensions()"),
    ("ext_modules_triple_quote", "'''\next_modules = []\n'''"),
    ("ext_modules_fstring", "print(f'{ext_modules}')"),
    ("ext_modules_class_attr", "class C:\n    ext_modules = []"),
    ("ext_modules_lambda", "f = lambda: ext_modules"),
    ("ext_modules_import_line", "from foo import ext_modules"),
]

for name, snippet in _ext_modules_snippets:
    _C_EXT_KEYWORD_CASES.append(
        pytest.param(snippet, id=f"c_ext-{name}")
    )

# --- Extension( variations ---
_extension_call_snippets = [
    ("Extension_basic", "Extension('foo', ['foo.c'])"),
    ("Extension_multiline", "Extension(\n    'foo',\n    sources=['foo.c'],\n)"),
    ("Extension_with_import", "from setuptools import Extension\nExtension('x', ['x.c'])"),
    ("Extension_distutils", "from distutils.core import Extension\nExtension('y', ['y.c'])"),
    ("Extension_cython", "from Cython.Build import cythonize\nExtension('z', ['z.pyx'])"),
    ("Extension_commented", "# Extension('a', ['a.c'])"),
    ("Extension_in_string", 'x = "Extension(foo)"'),
    ("Extension_nested", "setup(ext_modules=[Extension('b', ['b.c'])])"),
    ("Extension_subclass", "class MyExtension(Extension):\n    pass"),
    ("Extension_method", "obj.Extension('c', ['c.c'])"),
    ("Extension_late_file", "\n" * 100 + "Extension('d', ['d.c'])"),
    ("Extension_early_file", "Extension('e', ['e.c'])\n" + "\n" * 100),
    ("Extension_with_kwargs", "Extension('f', sources=['f.c'], include_dirs=['/usr/include'])"),
    ("Extension_star_import", "from setuptools import *\nExtension('g', ['g.c'])"),
    ("Extension_in_list", "exts = [Extension('h', ['h.c']), Extension('i', ['i.c'])]"),
    ("Extension_numpy_ext", "from numpy.distutils.core import Extension\nExtension('j', ['j.f90'])"),
    ("Extension_define_macros", "Extension('k', ['k.c'], define_macros=[('A', '1')])"),
    ("Extension_libraries", "Extension('l', ['l.c'], libraries=['m'])"),
    ("Extension_include", "Extension('n', ['n.c'], include_dirs=['include/'])"),
    ("Extension_language_cpp", "Extension('o', ['o.cpp'], language='c++')"),
    ("Extension_pyx", "Extension('p', ['p.pyx'])"),
    ("Extension_multiple_sources", "Extension('q', ['q1.c', 'q2.c', 'q3.c'])"),
    ("Extension_extra_args", "Extension('r', ['r.c'], extra_compile_args=['-O3'])"),
    ("Extension_swig", "Extension('s', ['s.c', 's.i'])"),
    ("Extension_name_dot", "Extension('pkg.sub.mod', ['src/mod.c'])"),
    ("Extension_runtime_lib", "Extension('t', ['t.c'], runtime_library_dirs=['/usr/lib'])"),
    ("Extension_in_try", "try:\n    Extension('u', ['u.c'])\nexcept:\n    pass"),
    ("Extension_in_if", "if sys.platform == 'linux':\n    Extension('v', ['v.c'])"),
    ("Extension_assigned", "e = Extension('w', ['w.c'])"),
    ("Extension_appended", "exts.append(Extension('x', ['x.c']))"),
]

for name, snippet in _extension_call_snippets:
    _C_EXT_KEYWORD_CASES.append(
        pytest.param(snippet, id=f"c_ext-{name}")
    )

# --- cythonize variations ---
_cythonize_snippets = [
    ("cythonize_basic", "ext_modules=cythonize(extensions)"),
    ("cythonize_list", "cythonize([Extension('a', ['a.pyx'])])"),
    ("cythonize_glob", "cythonize('src/*.pyx')"),
    ("cythonize_import", "from Cython.Build import cythonize\ncythonize(exts)"),
    ("cythonize_commented", "# cythonize(exts)"),
    ("cythonize_string", 'x = "cythonize is great"'),
    ("cythonize_multiline", "cythonize(\n    extensions,\n    compiler_directives={'boundscheck': False},\n)"),
    ("cythonize_nthreads", "cythonize(exts, nthreads=4)"),
    ("cythonize_annotate", "cythonize(exts, annotate=True)"),
    ("cythonize_language_level", "cythonize(exts, language_level='3')"),
    ("cythonize_in_try", "try:\n    cythonize(exts)\nexcept ImportError:\n    pass"),
    ("cythonize_conditional", "exts = cythonize(exts) if USE_CYTHON else exts"),
    ("cythonize_late", "\n" * 80 + "cythonize(exts)"),
    ("cythonize_early", "cythonize(exts)\n" + "\n" * 80),
    ("cythonize_with_ext_modules", "ext_modules = cythonize(extensions)"),
    ("cythonize_force", "cythonize(exts, force=True)"),
    ("cythonize_build_dir", "cythonize(exts, build_dir='build')"),
    ("cythonize_compiler_dir", "cythonize(exts, compiler_directives={'language_level': '3'})"),
    ("cythonize_wrapped", "result = cythonize(\n    get_extensions()\n)"),
    ("cythonize_assigned_var", "cy_exts = cythonize(raw_exts)"),
]

for name, snippet in _cythonize_snippets:
    _C_EXT_KEYWORD_CASES.append(
        pytest.param(snippet, id=f"c_ext-{name}")
    )

# --- Surrounding context variations ---
_context_variations = [
    ("minimal_setup", "from setuptools import setup\nsetup(ext_modules=[])"),
    ("full_setup", "from setuptools import setup, Extension\nsetup(\n    name='pkg',\n    version='1.0',\n    ext_modules=[Extension('m', ['m.c'])],\n)"),
    ("shebang_and_ext", "#!/usr/bin/env python\next_modules = []"),
    ("encoding_and_ext", "# -*- coding: utf-8 -*-\next_modules = []"),
    ("long_docstring_ext", '"""' + "x" * 500 + '"""\next_modules = []'),
    ("mixed_keywords", "ext_modules = cythonize([Extension('a', ['a.pyx'])])"),
    ("all_three_keywords", "from Cython.Build import cythonize\nfrom setuptools import Extension\next_modules = cythonize([Extension('a', ['a.pyx'])])"),
    ("unicode_content_ext", "# Unicode: café résumé\next_modules = []"),
    ("empty_lines_ext", "\n\n\n\n\next_modules = []\n\n\n\n"),
    ("tabs_and_spaces_ext", "\t ext_modules\t=\t[]\t"),
    ("windows_line_endings", "ext_modules = []\r\nsetup()\r\n"),
    ("just_keyword_alone", "ext_modules"),
    ("keyword_in_comment_block", "# This module uses ext_modules\n# and Extension(\n# and cythonize"),
    ("keyword_substring_extmodules", "my_ext_modules_list = []"),
    ("keyword_at_eof_no_newline", "x = 1\next_modules = []"),
    ("multiline_string_ext", "s = '''\next_modules = []\n'''"),
    ("raw_string_ext", r"s = r'ext_modules = []'"),
    ("bytes_like_ext", "b'ext_modules'  # not really bytes but has keyword"),
    ("decorator_ext", "@some_decorator\ndef get_ext_modules(): pass"),
    ("nested_function_ext", "def outer():\n    def inner():\n        ext_modules = []\n    return inner"),
]

for name, snippet in _context_variations:
    _C_EXT_KEYWORD_CASES.append(
        pytest.param(snippet, id=f"c_ext-ctx-{name}")
    )

# --- Additional padding to reach ~200 ---
_extra_c_ext = []
for i in range(100):
    _extra_c_ext.append(
        pytest.param(
            f"# line {i}\next_modules = [Extension('mod{i}', ['mod{i}.c'])]",
            id=f"c_ext-varied_ext_modules_{i:03d}",
        )
    )
for i in range(20):
    _extra_c_ext.append(
        pytest.param(
            f"from setuptools import Extension\nExT_mOdUlEs = []\next_modules = get_ext_{i}()",
            id=f"c_ext-case_sensitive_{i:03d}",
        )
    )


@pytest.mark.parametrize("setup_content", _C_EXT_KEYWORD_CASES + _extra_c_ext)
def test_c_ext_triggers_build_essential(tmp_path, setup_content):
    _setup_repo(tmp_path, setup_py=setup_content)
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert result[0] == BUILD
    assert MESON not in result
    assert GFORTRAN not in result
    assert OPENBLAS not in result
    assert len(result) == 1


# =====================================================================
# Category 2: meson.build exists (~150 tests)
# =====================================================================

_MESON_CONTENT_CASES = []

_meson_contents = [
    ("empty", ""),
    ("minimal", "project('foo', 'c')"),
    ("cpp_project", "project('bar', 'cpp', version: '1.0')"),
    ("with_deps", "project('baz', 'c')\ndep = dependency('glib-2.0')"),
    ("executable", "project('x', 'c')\nexecutable('x', 'x.c')"),
    ("library", "project('y', 'c')\nlibrary('y', 'y.c')"),
    ("shared_library", "project('z', 'c')\nshared_library('z', 'z.c')"),
    ("static_library", "project('w', 'c')\nstatic_library('w', 'w.c')"),
    ("subdir", "project('a', 'c')\nsubdir('src')"),
    ("install_headers", "project('b', 'c')\ninstall_headers('b.h')"),
    ("meson_version", "project('c', 'c', meson_version: '>=0.50')"),
    ("fortran_project", "project('d', 'fortran')"),
    ("mixed_lang", "project('e', 'c', 'fortran')"),
    ("long_file", "project('f', 'c')\n" + "# comment\n" * 200),
    ("unicode_content", "# Unicode: café\nproject('g', 'c')"),
    ("windows_endings", "project('h', 'c')\r\n"),
    ("tabs", "\tproject('i', 'c')"),
    ("comments_only", "# This is just comments\n# Nothing else"),
    ("complex_build", "project('j', 'c', 'cpp')\npy = import('python').find_installation()\npy.extension_module('mod', 'mod.c')"),
    ("numpy_meson", "project('numpy', 'c', 'cpp', 'cython')\nnumpy_nodepr = '-DNPY_NO_DEPRECATED_API'"),
    ("scipy_meson", "project('scipy', 'c', 'cpp', 'cython', 'fortran')"),
    ("meson_options", "option('debug', type: 'boolean', value: false)"),
    ("test_config", "project('k', 'c')\ntest('test_k', executable('test_k', 'test_k.c'))"),
    ("pkg_config", "project('l', 'c')\npkg = import('pkgconfig')"),
    ("custom_target", "project('m', 'c')\ncustom_target('gen', output: 'gen.c', command: ['gen.py'])"),
    ("with_if", "project('n', 'c')\nif get_option('debug')\n  add_global_arguments('-g', language: 'c')\nendif"),
    ("vcs_tag", "project('o', 'c')\nvcs = vcs_tag(command: ['git', 'describe'])"),
    ("compiler_check", "project('p', 'c')\ncc = meson.get_compiler('c')\ncc.has_header('stdio.h')"),
    ("feature_option", "project('q', 'c')\nfeature = get_option('feature')"),
    ("default_options", "project('r', 'c', default_options: ['warning_level=3'])"),
]

for name, content in _meson_contents:
    _MESON_CONTENT_CASES.append(pytest.param(content, id=f"meson-{name}"))

# Additional meson cases with varying content
for i in range(70):
    _MESON_CONTENT_CASES.append(
        pytest.param(
            f"project('pkg{i}', 'c')\n# build line {i}",
            id=f"meson-varied_{i:03d}",
        )
    )

# Additional meson with different project languages
_meson_langs = ["c", "cpp", "fortran", "cython", "rust", "java", "d", "objc",
                "objcpp", "vala"]
for idx, lang in enumerate(_meson_langs):
    _MESON_CONTENT_CASES.append(
        pytest.param(
            f"project('lang_{lang}', '{lang}')",
            id=f"meson-lang_{lang}",
        )
    )

# Meson with large content
for i in range(40):
    _MESON_CONTENT_CASES.append(
        pytest.param(
            f"project('big{i}', 'c')\n" + "\n".join(
                f"lib{j} = library('lib{j}', 'lib{j}.c')" for j in range(i + 1)
            ),
            id=f"meson-big_{i:03d}",
        )
    )


@pytest.mark.parametrize("meson_content", _MESON_CONTENT_CASES)
def test_meson_build_triggers_meson_and_build_essential(tmp_path, meson_content):
    _setup_repo(tmp_path, meson=meson_content)
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert MESON in result
    assert result[0] == BUILD
    assert result[1] == MESON
    assert GFORTRAN not in result
    assert OPENBLAS not in result
    assert len(result) == 2


_MESON_NESTED_CASES = []
_nested_meson_dirs = [
    "sub/meson.build",
    "src/meson.build",
    "lib/meson.build",
    "a/b/meson.build",
    "deep/nested/dir/meson.build",
]
for d in _nested_meson_dirs:
    _MESON_NESTED_CASES.append(pytest.param(d, id=f"meson_nested-{d.replace('/', '_')}"))


@pytest.mark.parametrize("nested_path", _MESON_NESTED_CASES)
def test_nested_meson_build_not_detected(tmp_path, nested_path):
    _setup_repo(tmp_path, files=[(nested_path, "project('x', 'c')")])
    result = detect_pre_install(tmp_path)
    assert result == []


# =====================================================================
# Category 3: Fortran files (~200 tests)
# =====================================================================

_FORTRAN_TOP_LEVEL_CASES = []

_fortran_exts = [".f90", ".f", ".f77", ".for"]
_fortran_names = [
    "main", "solver", "compute", "matrix", "fft", "blas_impl", "lapack_impl",
    "numeric", "integration", "ode", "pde", "interpolate", "optimize",
    "linalg", "signal", "special", "stats", "random", "sparse", "io_mod",
    "utils", "helpers", "core", "wrapper", "interface", "types", "constants",
    "precision", "kinds", "module_a", "module_b",
]

for ext in _fortran_exts:
    for name in _fortran_names:
        fname = f"{name}{ext}"
        _FORTRAN_TOP_LEVEL_CASES.append(
            pytest.param(fname, id=f"fortran_top-{fname}")
        )

# Extra top-level with numeric/special names
for i in range(20):
    for ext in _fortran_exts:
        _FORTRAN_TOP_LEVEL_CASES.append(
            pytest.param(f"file{i}{ext}", id=f"fortran_top-file{i}{ext}")
        )


@pytest.mark.parametrize("filename", _FORTRAN_TOP_LEVEL_CASES)
def test_fortran_top_level_triggers_gfortran(tmp_path, filename):
    (tmp_path / filename).write_text("! Fortran source\nprogram main\nend program", encoding="utf-8")
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert GFORTRAN in result
    assert result[0] == BUILD
    assert MESON not in result
    assert OPENBLAS not in result


_FORTRAN_ONE_DEEP_CASES = []

_fortran_subdirs = ["src", "lib", "fortran", "f90", "fcode", "numerical", "core",
                    "vendor", "extern", "third_party"]

for subdir in _fortran_subdirs:
    for ext in _fortran_exts:
        for name in ["solver", "compute", "main"]:
            fname = f"{subdir}/{name}{ext}"
            _FORTRAN_ONE_DEEP_CASES.append(
                pytest.param(fname, id=f"fortran_deep-{fname.replace('/', '_')}")
            )

# Extra one-deep variations
for i in range(20):
    for ext in _fortran_exts:
        _FORTRAN_ONE_DEEP_CASES.append(
            pytest.param(f"sub{i}/code{ext}", id=f"fortran_deep-sub{i}_code{ext}")
        )


@pytest.mark.parametrize("filepath", _FORTRAN_ONE_DEEP_CASES)
def test_fortran_one_level_deep_triggers_gfortran(tmp_path, filepath):
    p = tmp_path / filepath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("! Fortran source\nprogram main\nend program", encoding="utf-8")
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert GFORTRAN in result
    assert result[0] == BUILD


_FORTRAN_TOO_DEEP_CASES = []

_deep_paths = [
    "a/b/solver.f90", "a/b/c/solver.f", "x/y/z/mod.f77", "deep/nested/code.for",
    "src/sub/deep/code.f90", "lib/a/b/code.f", "a/b/c/d/code.f77",
]

for p in _deep_paths:
    _FORTRAN_TOO_DEEP_CASES.append(
        pytest.param(p, id=f"fortran_todeep-{p.replace('/', '_')}")
    )

# Extra deep paths
for i in range(13):
    for ext in _fortran_exts:
        _FORTRAN_TOO_DEEP_CASES.append(
            pytest.param(
                f"a/b/deep{i}{ext}",
                id=f"fortran_todeep-a_b_deep{i}{ext}",
            )
        )


@pytest.mark.parametrize("filepath", _FORTRAN_TOO_DEEP_CASES)
def test_fortran_two_levels_deep_not_detected(tmp_path, filepath):
    p = tmp_path / filepath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("! Fortran\nprogram main\nend program", encoding="utf-8")
    result = detect_pre_install(tmp_path)
    assert GFORTRAN not in result


# =====================================================================
# Category 4: BLAS/LAPACK (~200 tests)
# =====================================================================

_BLAS_SETUP_PY_CASES = []

_blas_keywords_in_setup = [
    ("blas_lower", "libraries = ['blas']"),
    ("BLAS_upper", "libraries = ['BLAS']"),
    ("Blas_mixed", "libraries = ['Blas']"),
    ("blas_in_comment", "# uses blas"),
    ("blas_in_string", 'desc = "links to blas"'),
    ("blas_in_name", "name='pyblas'"),
    ("blas_dep", "install_requires=['scipy']  # uses blas"),
    ("blas_ext_lib", "Extension('x', ['x.c'], libraries=['blas'])"),
    ("lapack_lower", "libraries = ['lapack']"),
    ("LAPACK_upper", "libraries = ['LAPACK']"),
    ("Lapack_mixed", "libraries = ['Lapack']"),
    ("lapack_in_comment", "# needs lapack"),
    ("lapack_in_string", 'x = "lapack is needed"'),
    ("lapack_ext_lib", "Extension('y', ['y.c'], libraries=['lapack'])"),
    ("openblas_lower", "libraries = ['openblas']"),
    ("OpenBLAS_upper", "libraries = ['OpenBLAS']"),
    ("OPENBLAS_allcaps", "libraries = ['OPENBLAS']"),
    ("openblas_in_comment", "# link to openblas"),
    ("openblas_in_define", "define_macros=[('USE_OPENBLAS', '1')]"),
    ("blas_lapack_both", "libraries = ['blas', 'lapack']"),
    ("all_three_blas", "libraries = ['openblas', 'blas', 'lapack']"),
    ("blas_substring", "library_name = 'libcblas'"),
    ("lapack_substring", "library_name = 'liblapack'"),
    ("openblas_substring", "library_name = 'libopenblas'"),
    ("blas_in_url", "url = 'https://github.com/blas/project'"),
    ("blas_in_path", "include_dirs = ['/usr/include/blas']"),
    ("lapack_in_path", "include_dirs = ['/usr/include/lapack']"),
    ("blas_define", "#define HAVE_BLAS 1"),
    ("lapack_define", "#define HAVE_LAPACK 1"),
    ("openblas_path", "extra_link_args = ['-L/opt/openblas/lib']"),
    ("blas_cfg_line", "blas_opt = get_blas_opt()"),
    ("lapack_cfg_line", "lapack_opt = get_lapack_opt()"),
    ("blas_class", "class BlasConfig:\n    pass"),
    ("blas_import", "from numpy.distutils.system_info import blas_info"),
    ("lapack_import", "from numpy.distutils.system_info import lapack_info"),
    ("blas_env_var", "os.environ.get('BLAS')"),
    ("lapack_env_var", "os.environ.get('LAPACK')"),
    ("blas_check_fn", "def check_blas():\n    pass"),
    ("lapack_check_fn", "def check_lapack():\n    pass"),
    ("openblas_threads", "os.environ['OPENBLAS_NUM_THREADS'] = '1'"),
]

for name, content in _blas_keywords_in_setup:
    _BLAS_SETUP_PY_CASES.append(pytest.param(content, None, id=f"blas_setup-{name}"))

# Extra BLAS in setup.py cases
for i in range(40):
    _BLAS_SETUP_PY_CASES.append(
        pytest.param(
            f"# config line {i}\nlibraries = ['blas_{i}']  # blas variant",
            None,
            id=f"blas_setup-variant_{i:03d}",
        )
    )


_BLAS_PYPROJECT_CASES = []

_blas_keywords_in_pyproject = [
    ("blas_dep", '[project]\ndependencies = ["scipy"]  # uses blas'),
    ("BLAS_dep_upper", '[project]\ndependencies = ["scipy"]  # BLAS'),
    ("blas_in_name", '[project]\nname = "pyblas"'),
    ("lapack_dep", '[project]\ndependencies = ["scipy"]  # needs lapack'),
    ("LAPACK_upper", '[project]\n# LAPACK config'),
    ("openblas_dep", '[project]\n# openblas is used'),
    ("OpenBLAS_mixed", '[project]\n# Uses OpenBLAS'),
    ("blas_in_desc", '[project]\ndescription = "Fast blas bindings"'),
    ("lapack_in_desc", '[project]\ndescription = "LAPACK wrapper"'),
    ("openblas_in_desc", '[project]\ndescription = "OpenBLAS interface"'),
    ("blas_in_extras", '[project.optional-dependencies]\ndev = ["blas-tools"]'),
    ("lapack_in_extras", '[project.optional-dependencies]\ndev = ["lapack-utils"]'),
    ("blas_build_req", '[build-system]\nrequires = ["numpy", "blas"]'),
    ("lapack_build_req", '[build-system]\nrequires = ["lapack"]'),
    ("openblas_build", '[build-system]\n# openblas required'),
    ("blas_in_readme", '[project]\nreadme = "README_blas.md"'),
    ("blas_in_url", '[project.urls]\nhome = "https://blas.example.com"'),
    ("lapack_in_url", '[project.urls]\nhome = "https://lapack.org"'),
    ("blas_tool_config", '[tool.cibuildwheel]\nbefore-all = "apt-get install -y libblas-dev"'),
    ("lapack_tool_config", '[tool.cibuildwheel]\nbefore-all = "apt-get install -y liblapack-dev"'),
    ("openblas_tool_config", '[tool.cibuildwheel]\nbefore-all = "apt-get install -y libopenblas-dev"'),
    ("blas_meson_opt", '[tool.meson-python]\n# blas configuration'),
    ("blas_scikit", '[project]\ndependencies = ["scikit-learn"]  # blas dep'),
    ("blas_numpy_dep", '[project]\ndependencies = ["numpy"]  # blas backend'),
    ("blas_comment_only", '# blas is needed for this project'),
    ("lapack_comment_only", '# lapack is a dependency'),
    ("openblas_comment_only", '# openblas should be installed'),
    ("blas_in_classifiers", '[project]\nclassifiers = ["Topic :: Scientific :: blas"]'),
    ("blas_multiline", '[project]\ndescription = """\nThis project uses\nblas for linear algebra\n"""'),
    ("lapack_multiline", '[project]\ndescription = """\nThis project uses\nlapack for factorization\n"""'),
]

for name, content in _blas_keywords_in_pyproject:
    _BLAS_PYPROJECT_CASES.append(pytest.param(None, content, id=f"blas_pyproj-{name}"))

# Extra BLAS in pyproject cases
for i in range(40):
    _BLAS_PYPROJECT_CASES.append(
        pytest.param(
            None,
            f"[project]\n# line {i}\ndescription = 'Uses blas variant {i}'",
            id=f"blas_pyproj-variant_{i:03d}",
        )
    )


@pytest.mark.parametrize("setup_content,pyproject_content", _BLAS_SETUP_PY_CASES + _BLAS_PYPROJECT_CASES)
def test_blas_lapack_triggers_openblas(tmp_path, setup_content, pyproject_content):
    _setup_repo(tmp_path, setup_py=setup_content, pyproject=pyproject_content)
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert OPENBLAS in result
    assert result[0] == BUILD


# BLAS case insensitivity tests
_BLAS_CASE_CASES = []

_case_variants = [
    "blas", "BLAS", "Blas", "bLaS", "BlAs", "bLAS", "BLAs", "BLas",
    "lapack", "LAPACK", "Lapack", "lApAcK", "LaPaCk", "lAPACK",
    "openblas", "OPENBLAS", "OpenBLAS", "Openblas", "openBLAS", "OPENBLAS",
    "OpenBlas", "openBlas", "oPeNbLaS",
]

for variant in _case_variants:
    _BLAS_CASE_CASES.append(
        pytest.param(
            f'desc = "{variant}"',
            None,
            id=f"blas_case-setup_{variant}",
        )
    )
    _BLAS_CASE_CASES.append(
        pytest.param(
            None,
            f'[project]\ndescription = "{variant}"',
            id=f"blas_case-pyproj_{variant}",
        )
    )


@pytest.mark.parametrize("setup_content,pyproject_content", _BLAS_CASE_CASES)
def test_blas_case_insensitive(tmp_path, setup_content, pyproject_content):
    _setup_repo(tmp_path, setup_py=setup_content, pyproject=pyproject_content)
    result = detect_pre_install(tmp_path)
    assert BUILD in result
    assert OPENBLAS in result
    assert result[0] == BUILD


# =====================================================================
# Category 5: Combinations (~200 tests)
# =====================================================================

_COMBO_CASES = []

# All 4 triggers
_COMBO_CASES.append(pytest.param(
    "ext_modules = []", "project('x', 'c')", "solver.f90",
    '[project]\ndescription = "uses blas"',
    [BUILD, MESON, GFORTRAN, OPENBLAS],
    id="combo-all_four",
))

# C ext + meson
for i in range(15):
    _COMBO_CASES.append(pytest.param(
        f"ext_modules = [Extension('m{i}', ['m{i}.c'])]",
        f"project('p{i}', 'c')", None, None,
        [BUILD, MESON],
        id=f"combo-c_ext_meson_{i:03d}",
    ))

# C ext + fortran
for ext in _fortran_exts:
    for i in range(8):
        _COMBO_CASES.append(pytest.param(
            f"ext_modules = [Extension('f{i}', ['f{i}.c'])]",
            None, f"calc{i}{ext}", None,
            [BUILD, GFORTRAN],
            id=f"combo-c_ext_fortran_{ext}_{i:03d}",
        ))

# C ext + blas
for i in range(15):
    _COMBO_CASES.append(pytest.param(
        f"ext_modules = []\nlibraries = ['blas_{i}']  # blas",
        None, None, None,
        [BUILD, OPENBLAS],
        id=f"combo-c_ext_blas_{i:03d}",
    ))

# Meson + fortran
for ext in _fortran_exts:
    for i in range(5):
        _COMBO_CASES.append(pytest.param(
            None, f"project('mf{i}', 'c', 'fortran')",
            f"code{i}{ext}", None,
            [BUILD, MESON, GFORTRAN],
            id=f"combo-meson_fortran_{ext}_{i:03d}",
        ))

# Meson + blas
for i in range(15):
    _COMBO_CASES.append(pytest.param(
        None, f"project('mb{i}', 'c')", None,
        f"[project]\n# blas used in project {i}",
        [BUILD, MESON, OPENBLAS],
        id=f"combo-meson_blas_{i:03d}",
    ))

# Fortran + blas
for ext in _fortran_exts:
    for i in range(5):
        _COMBO_CASES.append(pytest.param(
            None, None, f"linalg{i}{ext}",
            f"[project]\n# lapack for project {i}",
            [BUILD, GFORTRAN, OPENBLAS],
            id=f"combo-fortran_blas_{ext}_{i:03d}",
        ))

# C ext + meson + fortran
for ext in _fortran_exts:
    for i in range(3):
        _COMBO_CASES.append(pytest.param(
            f"ext_modules = [Extension('x{i}', ['x{i}.c'])]",
            f"project('cmf{i}', 'c')", f"solve{i}{ext}", None,
            [BUILD, MESON, GFORTRAN],
            id=f"combo-c_meson_fortran_{ext}_{i:03d}",
        ))

# C ext + meson + blas
for i in range(10):
    _COMBO_CASES.append(pytest.param(
        f"ext_modules = [Extension('b{i}', ['b{i}.c'])]\n# blas",
        f"project('cmb{i}', 'c')", None, None,
        [BUILD, MESON, OPENBLAS],
        id=f"combo-c_meson_blas_{i:03d}",
    ))

# C ext + fortran + blas
for ext in _fortran_exts:
    for i in range(3):
        _COMBO_CASES.append(pytest.param(
            f"ext_modules = [Extension('cfb{i}', ['cfb{i}.c'])]\n# lapack",
            None, f"mat{i}{ext}", None,
            [BUILD, GFORTRAN, OPENBLAS],
            id=f"combo-c_fortran_blas_{ext}_{i:03d}",
        ))

# Meson + fortran + blas
for ext in _fortran_exts:
    for i in range(3):
        _COMBO_CASES.append(pytest.param(
            None, f"project('mfb{i}', 'c', 'fortran')",
            f"num{i}{ext}",
            f"[project]\n# openblas for project {i}",
            [BUILD, MESON, GFORTRAN, OPENBLAS],
            id=f"combo-meson_fortran_blas_{ext}_{i:03d}",
        ))

# All four with different keywords
_all_four_variants = [
    ("ext_modules", "ext_modules = get_exts()"),
    ("Extension", "from setuptools import Extension\ne = Extension('a', ['a.c'])"),
    ("cythonize", "from Cython.Build import cythonize\ncythonize(exts)"),
]
for kw_name, setup_content in _all_four_variants:
    for ext in _fortran_exts:
        _COMBO_CASES.append(pytest.param(
            setup_content + "\n# blas needed",
            "project('all', 'c')", f"all{ext}", None,
            [BUILD, MESON, GFORTRAN, OPENBLAS],
            id=f"combo-all_four_{kw_name}_{ext}",
        ))

# BLAS from both setup.py and pyproject.toml
for i in range(10):
    _COMBO_CASES.append(pytest.param(
        f"# blas in setup {i}", None, None,
        f"[project]\n# lapack in pyproject {i}",
        [BUILD, OPENBLAS],
        id=f"combo-blas_both_files_{i:03d}",
    ))

# Meson only (no setup.py)
for i in range(10):
    _COMBO_CASES.append(pytest.param(
        None, f"project('monly{i}', 'c')", None, None,
        [BUILD, MESON],
        id=f"combo-meson_only_{i:03d}",
    ))

# Fortran only (no setup.py)
for ext in _fortran_exts:
    _COMBO_CASES.append(pytest.param(
        None, None, f"standalone{ext}", None,
        [BUILD, GFORTRAN],
        id=f"combo-fortran_only_{ext}",
    ))


@pytest.mark.parametrize(
    "setup_content,meson_content,fortran_file,pyproject_content,expected",
    _COMBO_CASES,
)
def test_combinations(tmp_path, setup_content, meson_content, fortran_file,
                      pyproject_content, expected):
    files = []
    if fortran_file:
        files.append((fortran_file, "! Fortran\nprogram main\nend program"))
    _setup_repo(
        tmp_path,
        setup_py=setup_content,
        pyproject=pyproject_content,
        meson=meson_content,
        files=files,
    )
    result = detect_pre_install(tmp_path)
    assert result == expected


# =====================================================================
# Category 6: No pre-install needed (~100 tests)
# =====================================================================

_NO_PREINSTALL_CASES = []

# Empty repo
_NO_PREINSTALL_CASES.append(pytest.param({}, id="no_pre-empty_repo"))

# Pure Python repos
_pure_python_setups = [
    ("pure_setup_minimal", {"setup_py": "from setuptools import setup\nsetup(name='pkg')"}),
    ("pure_setup_full", {"setup_py": "from setuptools import setup\nsetup(\n    name='pkg',\n    version='1.0',\n    packages=['pkg'],\n)"}),
    ("pure_setup_find", {"setup_py": "from setuptools import setup, find_packages\nsetup(packages=find_packages())"}),
    ("pure_setup_entry", {"setup_py": "from setuptools import setup\nsetup(entry_points={'console_scripts': ['cli=pkg:main']})"}),
    ("pure_setup_classifiers", {"setup_py": "from setuptools import setup\nsetup(classifiers=['Programming Language :: Python :: 3'])"}),
    ("pure_pyproject_minimal", {"pyproject": "[project]\nname = 'pkg'\nversion = '1.0'"}),
    ("pure_pyproject_full", {"pyproject": "[project]\nname = 'pkg'\nversion = '1.0'\n[build-system]\nrequires = ['setuptools']"}),
    ("pure_pyproject_poetry", {"pyproject": "[tool.poetry]\nname = 'pkg'\nversion = '1.0'\n[tool.poetry.dependencies]\npython = '^3.8'"}),
    ("pure_pyproject_flit", {"pyproject": "[build-system]\nrequires = ['flit_core']\n[project]\nname = 'pkg'"}),
    ("pure_pyproject_hatch", {"pyproject": "[build-system]\nrequires = ['hatchling']\n[project]\nname = 'pkg'"}),
    ("only_readme", {"files": [("README.md", "# My Project")]}),
    ("only_license", {"files": [("LICENSE", "MIT License")]}),
    ("only_py_files", {"files": [("pkg/__init__.py", ""), ("pkg/main.py", "print('hello')")]}),
    ("only_tests", {"files": [("tests/test_main.py", "def test_it(): pass")]}),
    ("only_docs", {"files": [("docs/index.rst", "Welcome\n=======")]}),
    ("only_config", {"files": [(".flake8", "[flake8]\nmax-line-length = 100")]}),
    ("only_gitignore", {"files": [(".gitignore", "*.pyc\n__pycache__/")]}),
    ("only_makefile", {"files": [("Makefile", "test:\n\tpytest")]}),
    ("only_dockerfile", {"files": [("Dockerfile", "FROM python:3.10")]}),
    ("only_ci", {"files": [(".github/workflows/ci.yml", "name: CI")]}),
    ("setup_no_ext", {"setup_py": "from setuptools import setup\nsetup(name='pkg', packages=['pkg'])"}),
    ("setup_with_data", {"setup_py": "from setuptools import setup\nsetup(package_data={'pkg': ['*.json']})"}),
    ("setup_with_scripts", {"setup_py": "from setuptools import setup\nsetup(scripts=['bin/cli'])"}),
    ("setup_zip_safe", {"setup_py": "from setuptools import setup\nsetup(zip_safe=False)"}),
    ("setup_python_requires", {"setup_py": "from setuptools import setup\nsetup(python_requires='>=3.8')"}),
    ("pyproject_no_blas", {"pyproject": "[project]\ndescription = 'A pure Python library'\n[build-system]\nrequires = ['setuptools']"}),
    ("pyproject_deps_no_blas", {"pyproject": "[project]\ndependencies = ['requests', 'click', 'numpy']"}),
    ("both_no_triggers", {"setup_py": "from setuptools import setup\nsetup(name='pkg')", "pyproject": "[project]\nname = 'pkg'"}),
]

for name, kwargs in _pure_python_setups:
    _NO_PREINSTALL_CASES.append(pytest.param(kwargs, id=f"no_pre-{name}"))

# Files that look like fortran but aren't in right place (2+ levels deep)
_fake_fortran_deep = [
    ("deep_f90", {"files": [("a/b/code.f90", "! deep fortran")]}),
    ("deep_f", {"files": [("a/b/code.f", "! deep fortran")]}),
    ("deep_f77", {"files": [("a/b/code.f77", "! deep fortran")]}),
    ("deep_for", {"files": [("a/b/code.for", "! deep fortran")]}),
    ("very_deep_f90", {"files": [("a/b/c/d/code.f90", "! very deep")]}),
    ("triple_deep_f", {"files": [("x/y/z/code.f", "! triple deep")]}),
]
for name, kwargs in _fake_fortran_deep:
    _NO_PREINSTALL_CASES.append(pytest.param(kwargs, id=f"no_pre-{name}"))

# Nested meson.build (not at root)
_nested_meson_no = [
    ("nested_meson_src", {"files": [("src/meson.build", "project('x', 'c')")]}),
    ("nested_meson_lib", {"files": [("lib/meson.build", "project('x', 'c')")]}),
    ("nested_meson_deep", {"files": [("a/b/meson.build", "project('x', 'c')")]}),
]
for name, kwargs in _nested_meson_no:
    _NO_PREINSTALL_CASES.append(pytest.param(kwargs, id=f"no_pre-{name}"))

# Similar keyword names that don't match
_no_match_keywords = [
    ("ext_module_no_s", {"setup_py": "ext_module = something"}),
    ("extensions_no_paren", {"setup_py": "extensions = [a, b, c]"}),
    ("Cythonize_capital", {"setup_py": "Cythonize(stuff)"}),
    ("extension_lower", {"setup_py": "extension('foo', ['foo.c'])"}),
    ("EXTENSION_upper", {"setup_py": "EXTENSION('foo', ['foo.c'])"}),
    ("ext_modules_in_pyproject", {"pyproject": "[project]\n# ext_modules not checked in pyproject"}),
]
for name, kwargs in _no_match_keywords:
    _NO_PREINSTALL_CASES.append(pytest.param(kwargs, id=f"no_pre-{name}"))

# Non-fortran extensions
_non_fortran = [
    ("c_file", {"files": [("code.c", "int main() {}")]}),
    ("cpp_file", {"files": [("code.cpp", "int main() {}")]}),
    ("h_file", {"files": [("code.h", "#pragma once")]}),
    ("py_file", {"files": [("code.py", "print('hi')")]}),
    ("rs_file", {"files": [("code.rs", "fn main() {}")]}),
    ("go_file", {"files": [("code.go", "package main")]}),
    ("java_file", {"files": [("Code.java", "class Code {}")]}),
    ("f95_file", {"files": [("code.f95", "! not .f90 etc")]}),
    ("fpp_file", {"files": [("code.fpp", "! preprocessor")]}),
    ("f03_file", {"files": [("code.f03", "! fortran 2003")]}),
    ("f08_file", {"files": [("code.f08", "! fortran 2008")]}),
]
for name, kwargs in _non_fortran:
    _NO_PREINSTALL_CASES.append(pytest.param(kwargs, id=f"no_pre-{name}"))

# Extra varied pure-python repos
for i in range(20):
    _NO_PREINSTALL_CASES.append(
        pytest.param(
            {"setup_py": f"from setuptools import setup\nsetup(name='pkg{i}', version='{i}.0')"},
            id=f"no_pre-pure_python_{i:03d}",
        )
    )


@pytest.mark.parametrize("repo_kwargs", _NO_PREINSTALL_CASES)
def test_no_pre_install_returns_empty(tmp_path, repo_kwargs):
    files = repo_kwargs.pop("files", None)
    setup_py = repo_kwargs.get("setup_py")
    pyproject = repo_kwargs.get("pyproject")
    _setup_repo(tmp_path, setup_py=setup_py, pyproject=pyproject, files=files)
    result = detect_pre_install(tmp_path)
    assert result == []


# =====================================================================
# Category 7: build-essential ordering (~150 tests)
# =====================================================================

_ORDERING_CASES = []

# build-essential at [0] with only meson
for i in range(20):
    _ORDERING_CASES.append(pytest.param(
        None, f"project('ord{i}', 'c')", None, None,
        [BUILD, MESON], 2,
        id=f"order-meson_only_{i:03d}",
    ))

# build-essential at [0] with only gfortran
for ext in _fortran_exts:
    for i in range(5):
        _ORDERING_CASES.append(pytest.param(
            None, None, f"ord{i}{ext}", None,
            [BUILD, GFORTRAN], 2,
            id=f"order-fortran_only_{ext}_{i:03d}",
        ))

# build-essential at [0] with only openblas
for i in range(20):
    _ORDERING_CASES.append(pytest.param(
        f"# blas in setup {i}",  None, None, None,
        [BUILD, OPENBLAS], 2,
        id=f"order-blas_setup_only_{i:03d}",
    ))

for i in range(20):
    _ORDERING_CASES.append(pytest.param(
        None, None, None,
        f"[project]\n# openblas variant {i}",
        [BUILD, OPENBLAS], 2,
        id=f"order-blas_pyproj_only_{i:03d}",
    ))

# build-essential at [0] with c ext only
for i in range(20):
    _ORDERING_CASES.append(pytest.param(
        f"ext_modules = [Extension('o{i}', ['o{i}.c'])]",
        None, None, None,
        [BUILD], 1,
        id=f"order-c_ext_only_{i:03d}",
    ))

# Order: BUILD, MESON, GFORTRAN
for ext in _fortran_exts:
    _ORDERING_CASES.append(pytest.param(
        None, "project('mf', 'c')", f"mf{ext}", None,
        [BUILD, MESON, GFORTRAN], 3,
        id=f"order-meson_fortran_{ext}",
    ))

# Order: BUILD, MESON, OPENBLAS
for i in range(5):
    _ORDERING_CASES.append(pytest.param(
        None, f"project('mo{i}', 'c')", None,
        f"[project]\n# blas config {i}",
        [BUILD, MESON, OPENBLAS], 3,
        id=f"order-meson_blas_{i:03d}",
    ))

# Order: BUILD, GFORTRAN, OPENBLAS
for ext in _fortran_exts:
    _ORDERING_CASES.append(pytest.param(
        f"# lapack config", None, f"linalg{ext}", None,
        [BUILD, GFORTRAN, OPENBLAS], 3,
        id=f"order-fortran_blas_{ext}",
    ))

# Order: BUILD, MESON, GFORTRAN, OPENBLAS (all)
for ext in _fortran_exts:
    for i in range(3):
        _ORDERING_CASES.append(pytest.param(
            f"ext_modules = []\n# blas dep {i}",
            f"project('full{i}', 'c')", f"full{i}{ext}", None,
            [BUILD, MESON, GFORTRAN, OPENBLAS], 4,
            id=f"order-all_four_{ext}_{i:03d}",
        ))

# C ext doesn't add its own command, just build-essential
for i in range(10):
    _ORDERING_CASES.append(pytest.param(
        f"ext_modules = [Extension('ce{i}', ['ce{i}.c'])]",
        f"project('ce{i}', 'c')", None, None,
        [BUILD, MESON], 2,
        id=f"order-c_ext_plus_meson_{i:03d}",
    ))


@pytest.mark.parametrize(
    "setup_content,meson_content,fortran_file,pyproject_content,expected,expected_len",
    _ORDERING_CASES,
)
def test_build_essential_ordering(tmp_path, setup_content, meson_content,
                                  fortran_file, pyproject_content,
                                  expected, expected_len):
    files = []
    if fortran_file:
        files.append((fortran_file, "! Fortran\nprogram main\nend program"))
    _setup_repo(
        tmp_path,
        setup_py=setup_content,
        pyproject=pyproject_content,
        meson=meson_content,
        files=files,
    )
    result = detect_pre_install(tmp_path)
    assert len(result) == expected_len
    assert result == expected
    if result:
        assert result[0] == BUILD
