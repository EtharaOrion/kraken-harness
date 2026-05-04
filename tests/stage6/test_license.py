import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import check_license

LICENSE_FILENAMES = [
    "LICENSE", "LICENSE.md", "LICENSE.txt",
    "LICENCE", "LICENCE.md", "LICENCE.txt",
    "COPYING", "COPYING.md",
]

# ============================================================
# Helpers
# ============================================================

def _write_license(tmp_path, filename, content):
    (tmp_path / filename).write_text(content, encoding="utf-8")


def _write_pyproject(tmp_path, content):
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent(content), encoding="utf-8")


# ============================================================
# 1. License files with pattern matching  (~500 cases)
# ============================================================

_MIT_TEXTS = [
    "MIT License",
    "mit license",
    "MIT LICENSE",
    "The MIT License",
    "The MIT License (MIT)",
    "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the \"Software\"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n\nMIT",
    "Permission is hereby granted ... MIT",
    "Permission is hereby granted\nfoo bar baz\nMIT",
    "Permission is hereby granted, free of charge\n\nMIT",
    "Copyright (c) 2023 Foo\n\nMIT License\n\nPermission is hereby granted...",
    "MIT License\nCopyright 2023",
    "  MIT License  ",
]

_MIT0_TEXTS = [
    "MIT-0",
    "MIT-0 License",
    "mit-0",
    "MIT No Attribution",
    "mit no attribution",
    "MIT NO ATTRIBUTION",
    "MIT No Attribution License",
    "The MIT-0 License",
    "This is the MIT-0 license.",
    "Licensed under MIT-0",
    "MIT No Attribution (MIT-0)",
    "Copyright 2023\nMIT-0",
]

_APACHE_TEXTS = [
    "Apache License\nVersion 2.0",
    "Apache License, Version 2.0",
    "apache license version 2.0",
    "APACHE LICENSE VERSION 2.0",
    "Apache License\n\nVersion 2.0, January 2004",
    "Licensed under the Apache License",
    "licensed under the apache license",
    "LICENSED UNDER THE APACHE LICENSE",
    "Licensed under the Apache License, Version 2.0",
    "Licensed under the Apache License, Version 2.0 (the \"License\")",
    "Copyright 2023 Foo\nLicensed under the Apache License, Version 2.0",
    "Apache License                           Version 2.0, January 2004",
]

_BSD3_TEXTS = [
    "BSD 3-Clause",
    "bsd 3-clause",
    "BSD 3-CLAUSE",
    "BSD 3-Clause License",
    "The BSD 3-Clause License",
    "BSD 3-Clause \"New\" or \"Revised\" License",
    "Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following three conditions are met",
    "Redistribution and use\nfoo\nthree conditions",
    "redistribution and use in source and binary forms three conditions",
    "REDISTRIBUTION AND USE ... THREE CONDITIONS",
    "Copyright (c) 2023\nBSD 3-Clause License",
    "BSD 3-Clause\nCopyright holder",
]

_BSD2_TEXTS = [
    "BSD 2-Clause",
    "bsd 2-clause",
    "BSD 2-CLAUSE",
    "BSD 2-Clause License",
    "The BSD 2-Clause License",
    "BSD 2-Clause \"Simplified\" License",
    "Simplified BSD",
    "simplified bsd",
    "SIMPLIFIED BSD",
    "Simplified BSD License",
    "The Simplified BSD License",
    "Copyright 2023\nBSD 2-Clause License",
]

_ISC_TEXTS = [
    "ISC License",
    "isc license",
    "ISC LICENSE",
    "The ISC License",
    "ISC License (ISC)",
    "ISC license",
    "Copyright (c) 2023\nISC License",
    "ISC License\nCopyright holder",
    "Permission to use, copy, modify\nISC License",
    "The ISC License\nSome extra text",
    "An ISC License for the project",
    "ISC license granted to all",
]

_PATTERN_MAP = {
    "MIT": _MIT_TEXTS,
    "MIT-0": _MIT0_TEXTS,
    "Apache-2.0": _APACHE_TEXTS,
    "BSD-3-Clause": _BSD3_TEXTS,
    "BSD-2-Clause": _BSD2_TEXTS,
    "ISC": _ISC_TEXTS,
}

_license_file_cases = []
for expected, texts in _PATTERN_MAP.items():
    for fname in LICENSE_FILENAMES:
        for text in texts:
            _license_file_cases.append((fname, text, expected))


@pytest.mark.parametrize("filename, content, expected", _license_file_cases,
                         ids=[f"{e}-{fn}-{i}" for i, (fn, _, e) in enumerate(_license_file_cases)])
def test_license_file_pattern(tmp_path, filename, content, expected):
    _write_license(tmp_path, filename, content)
    assert check_license(tmp_path) == expected


_extra_mit = [
    "Copyright 2024 FooCorp\n\nMIT License\n\nAll rights reserved.",
    "MIT License\n\n(c) 2024 BarInc",
    "== MIT License ==",
    "Permission is hereby granted, to use this software. MIT",
    "PERMISSION IS HEREBY GRANTED... MIT",
]

_extra_mit0 = [
    "Copyright 2024 Baz\nMIT-0\nSee docs for details.",
    "Distributed under MIT No Attribution terms.",
    "Project uses MIT-0 license.",
]

_extra_apache = [
    "Apache License\n   Version 2.0\n   January 2004",
    "Licensed under the Apache License v2",
    "LICENSED UNDER THE APACHE LICENSE, V2.0",
]

_extra_bsd3 = [
    "Copyright 2024\nBSD 3-Clause License\nAll rights reserved.",
    "Redistribution and use in source form three conditions apply",
    "This software is BSD 3-Clause licensed.",
]

_extra_bsd2 = [
    "Copyright 2024\nBSD 2-Clause\nPermissions apply.",
    "This is the Simplified BSD License.",
    "Released under Simplified BSD terms.",
]

_extra_isc = [
    "Copyright 2024\nISC License\nSee LICENSE.",
    "Provided under ISC license terms.",
    "Released under the ISC License.",
]

_EXTRA_MAP = {
    "MIT": _extra_mit,
    "MIT-0": _extra_mit0,
    "Apache-2.0": _extra_apache,
    "BSD-3-Clause": _extra_bsd3,
    "BSD-2-Clause": _extra_bsd2,
    "ISC": _extra_isc,
}

_extra_file_cases = []
for expected, texts in _EXTRA_MAP.items():
    for fname in LICENSE_FILENAMES:
        for text in texts:
            _extra_file_cases.append((fname, text, expected))


@pytest.mark.parametrize("filename, content, expected", _extra_file_cases,
                         ids=[f"extra-{e}-{fn}-{i}" for i, (fn, _, e) in enumerate(_extra_file_cases)])
def test_license_file_extra_variations(tmp_path, filename, content, expected):
    _write_license(tmp_path, filename, content)
    assert check_license(tmp_path) == expected


# ============================================================
# 2. pyproject.toml license field  (~300 cases)
# ============================================================

# In pyproject license field matching, MIT always matches before MIT-0
# because "MIT".upper() in "MIT-0".upper() is True and MIT is checked first.
# So pyproject license field "MIT-0" → "MIT".

_LICENSE_NAMES_NO_MIT0 = ["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC"]

# --- license as dict with "text" key (TOML inline table uses = not :) ---
_pyproject_text_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    for val in [lic, lic.upper(), lic.lower()]:
        _pyproject_text_cases.append((f'{{text = "{val}"}}', lic))

for val in ["Mit", "mIt", "MiT"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "MIT"))
for val in ["apache-2.0", "APACHE-2.0", "Apache-2.0"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "Apache-2.0"))
for val in ["bsd-3-clause", "BSD-3-CLAUSE", "Bsd-3-Clause"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "BSD-3-Clause"))
for val in ["bsd-2-clause", "BSD-2-CLAUSE", "Bsd-2-Clause"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "BSD-2-Clause"))
for val in ["isc", "ISC", "Isc"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "ISC"))
# MIT-0 in text field → matches MIT (MIT is checked first, "MIT" in "MIT-0")
for val in ["mit-0", "MIT-0", "Mit-0"]:
    _pyproject_text_cases.append((f'{{text = "{val}"}}', "MIT"))


@pytest.mark.parametrize("lic_field, expected", _pyproject_text_cases,
                         ids=[f"toml-text-{e}-{i}" for i, (_, e) in enumerate(_pyproject_text_cases)])
def test_pyproject_license_text(tmp_path, lic_field, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = {lic_field}
    """)
    assert check_license(tmp_path) == expected


# --- license as dict with "expression" key ---
_pyproject_expr_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    for val in [lic, lic.upper(), lic.lower()]:
        _pyproject_expr_cases.append((f'{{expression = "{val}"}}', lic))

for val in ["Mit", "mIt"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "MIT"))
for val in ["apache-2.0", "APACHE-2.0"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "Apache-2.0"))
for val in ["bsd-3-clause", "BSD-3-CLAUSE"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "BSD-3-Clause"))
for val in ["bsd-2-clause", "BSD-2-CLAUSE"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "BSD-2-Clause"))
for val in ["isc", "ISC"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "ISC"))
for val in ["mit-0", "MIT-0"]:
    _pyproject_expr_cases.append((f'{{expression = "{val}"}}', "MIT"))


@pytest.mark.parametrize("lic_field, expected", _pyproject_expr_cases,
                         ids=[f"toml-expr-{e}-{i}" for i, (_, e) in enumerate(_pyproject_expr_cases)])
def test_pyproject_license_expression(tmp_path, lic_field, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = {lic_field}
    """)
    assert check_license(tmp_path) == expected


# --- license as string ---
_pyproject_str_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    for val in [lic, lic.upper(), lic.lower()]:
        _pyproject_str_cases.append((val, lic))

for val in ["Mit", "mIt", "MiT", "miT"]:
    _pyproject_str_cases.append((val, "MIT"))
# MIT-0 as string → MIT (MIT checked first, "MIT" in "MIT-0" is True)
for val in ["mit-0", "MIT-0", "Mit-0", "mIT-0"]:
    _pyproject_str_cases.append((val, "MIT"))
for val in ["apache-2.0", "APACHE-2.0", "Apache-2.0", "aPACHE-2.0"]:
    _pyproject_str_cases.append((val, "Apache-2.0"))
for val in ["bsd-3-clause", "BSD-3-CLAUSE", "Bsd-3-Clause", "bSD-3-CLAUSE"]:
    _pyproject_str_cases.append((val, "BSD-3-Clause"))
for val in ["bsd-2-clause", "BSD-2-CLAUSE", "Bsd-2-Clause", "bSD-2-CLAUSE"]:
    _pyproject_str_cases.append((val, "BSD-2-Clause"))
for val in ["isc", "ISC", "Isc", "isC"]:
    _pyproject_str_cases.append((val, "ISC"))


@pytest.mark.parametrize("lic_str, expected", _pyproject_str_cases,
                         ids=[f"toml-str-{e}-{i}" for i, (_, e) in enumerate(_pyproject_str_cases)])
def test_pyproject_license_string(tmp_path, lic_str, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{lic_str}"
    """)
    assert check_license(tmp_path) == expected


# --- license field with surrounding text ---
_pyproject_surrounded_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    _pyproject_surrounded_cases.append((f"License: {lic}", lic))
    _pyproject_surrounded_cases.append((f"{lic} License", lic))
    _pyproject_surrounded_cases.append((f"Distributed under {lic}", lic))
    _pyproject_surrounded_cases.append((f"  {lic}  ", lic))
# MIT-0 surrounded → MIT (MIT substring match wins)
_pyproject_surrounded_cases.append(("License: MIT-0", "MIT"))
_pyproject_surrounded_cases.append(("MIT-0 License", "MIT"))
_pyproject_surrounded_cases.append(("Distributed under MIT-0", "MIT"))
_pyproject_surrounded_cases.append(("  MIT-0  ", "MIT"))


@pytest.mark.parametrize("lic_str, expected", _pyproject_surrounded_cases,
                         ids=[f"toml-surround-{e}-{i}" for i, (_, e) in enumerate(_pyproject_surrounded_cases)])
def test_pyproject_license_string_surrounded(tmp_path, lic_str, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{lic_str}"
    """)
    assert check_license(tmp_path) == expected


# --- license dict: text empty → expression fallback (TOML table syntax) ---
_pyproject_dict_expr_fallback = []
for lic in _LICENSE_NAMES_NO_MIT0:
    _pyproject_dict_expr_fallback.append((lic, lic))
_pyproject_dict_expr_fallback.append(("MIT-0", "MIT"))


@pytest.mark.parametrize("expr_val, expected", _pyproject_dict_expr_fallback,
                         ids=[f"toml-expr-fallback-{e}-{i}" for i, (_, e) in enumerate(_pyproject_dict_expr_fallback)])
def test_pyproject_license_dict_text_empty_expression_fallback(tmp_path, expr_val, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        [project.license]
        text = ""
        expression = "{expr_val}"
    """)
    assert check_license(tmp_path) == expected


# --- license dict: text present (takes priority over expression) ---
_pyproject_dict_text_prio = []
for lic in _LICENSE_NAMES_NO_MIT0:
    _pyproject_dict_text_prio.append((lic, lic))


@pytest.mark.parametrize("text_val, expected", _pyproject_dict_text_prio,
                         ids=[f"toml-text-prio-{e}-{i}" for i, (_, e) in enumerate(_pyproject_dict_text_prio)])
def test_pyproject_license_dict_text_over_expression(tmp_path, text_val, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        [project.license]
        text = "{text_val}"
        expression = "GPL-3.0"
    """)
    assert check_license(tmp_path) == expected


# ============================================================
# 3. pyproject.toml classifiers  (~200 cases)
# ============================================================

# Classifier logic:
# "mit" in cls AND "mit-0" not in cls → MIT
# "mit-0" in cls OR "no attribution" in cls → MIT-0
# BUT: if cls has "mit" (without "mit-0"), first check wins → MIT
# So "MIT No Attribution License" has "mit" and not "mit-0" → MIT!
# Only "MIT-0" or strings without "mit" but with "no attribution" → MIT-0

_classifier_mit_cases = [
    ("License :: OSI Approved :: MIT License", "MIT"),
    ("License :: OSI Approved :: MIT", "MIT"),
    ("License :: MIT License", "MIT"),
    ("License :: MIT", "MIT"),
    ("License :: OSI Approved :: MIT License (MIT)", "MIT"),
    # These contain "mit" but not "mit-0", so → MIT
    ("License :: OSI Approved :: MIT No Attribution License", "MIT"),
]

_classifier_mit0_cases = [
    # Only "mit-0" in cls triggers MIT-0 via first path
    ("License :: OSI Approved :: MIT-0 License", "MIT-0"),
    ("License :: MIT-0", "MIT-0"),
    ("License :: MIT-0 License", "MIT-0"),
    ("License :: OSI Approved :: MIT-0", "MIT-0"),
    # "no attribution" without "mit" → MIT-0 via second path
    ("License :: No Attribution", "MIT-0"),
    ("License :: OSI Approved :: No Attribution License", "MIT-0"),
]

_classifier_apache_cases = [
    ("License :: OSI Approved :: Apache Software License 2.0", "Apache-2.0"),
    ("License :: OSI Approved :: Apache 2.0", "Apache-2.0"),
    ("License :: Apache 2.0", "Apache-2.0"),
    ("License :: OSI Approved :: Apache Software License v2.0", "Apache-2.0"),
    ("License :: Apache License 2.0", "Apache-2.0"),
]

_classifier_bsd3_cases = [
    ("License :: OSI Approved :: BSD License 3-Clause", "BSD-3-Clause"),
    ("License :: OSI Approved :: BSD 3-Clause License", "BSD-3-Clause"),
    ("License :: BSD 3", "BSD-3-Clause"),
    ("License :: OSI Approved :: BSD License (3-Clause)", "BSD-3-Clause"),
    ("License :: BSD-3-Clause", "BSD-3-Clause"),
]

_classifier_bsd2_cases = [
    ("License :: OSI Approved :: BSD License 2-Clause", "BSD-2-Clause"),
    ("License :: OSI Approved :: BSD 2-Clause License", "BSD-2-Clause"),
    ("License :: BSD 2", "BSD-2-Clause"),
    ("License :: OSI Approved :: BSD License (2-Clause)", "BSD-2-Clause"),
    ("License :: BSD-2-Clause", "BSD-2-Clause"),
]

_classifier_isc_cases = [
    ("License :: OSI Approved :: ISC License (ISCL)", "ISC"),
    ("License :: OSI Approved :: ISC License", "ISC"),
    ("License :: ISC", "ISC"),
    ("License :: OSI Approved :: ISC", "ISC"),
    ("License :: ISC License", "ISC"),
]

_all_classifier_cases = (
    _classifier_mit_cases + _classifier_mit0_cases +
    _classifier_apache_cases + _classifier_bsd3_cases +
    _classifier_bsd2_cases + _classifier_isc_cases
)


@pytest.mark.parametrize("classifier, expected", _all_classifier_cases,
                         ids=[f"cls-{e}-{i}" for i, (_, e) in enumerate(_all_classifier_cases)])
def test_pyproject_classifier_single(tmp_path, classifier, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        classifiers = ["{classifier}"]
    """)
    assert check_license(tmp_path) == expected


# --- Classifiers with extra non-license classifiers ---
_classifier_with_extras_cases = []
_extra_classifiers = [
    "Programming Language :: Python :: 3",
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Libraries",
    "Operating System :: OS Independent",
]

for cls, expected in _all_classifier_cases:
    for extra in _extra_classifiers:
        _classifier_with_extras_cases.append((cls, extra, expected))


@pytest.mark.parametrize("lic_cls, extra_cls, expected", _classifier_with_extras_cases[:120],
                         ids=[f"cls-extra-{e}-{i}" for i, (_, _, e) in enumerate(_classifier_with_extras_cases[:120])])
def test_pyproject_classifier_with_extras(tmp_path, lic_cls, extra_cls, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        classifiers = [
            "{extra_cls}",
            "{lic_cls}",
        ]
    """)
    assert check_license(tmp_path) == expected


@pytest.mark.parametrize("lic_cls, extra_cls, expected", _classifier_with_extras_cases[120:180],
                         ids=[f"cls-after-{e}-{i}" for i, (_, _, e) in enumerate(_classifier_with_extras_cases[120:180])])
def test_pyproject_classifier_license_after_extras(tmp_path, lic_cls, extra_cls, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        classifiers = [
            "{extra_cls}",
            "Programming Language :: Python :: 3.10",
            "{lic_cls}",
        ]
    """)
    assert check_license(tmp_path) == expected


# ============================================================
# 4. No license → None  (~50 cases)
# ============================================================

_no_license_texts = [
    "This is a random text file.",
    "Copyright 2023 Foo. All rights reserved.",
    "Some software license terms apply.",
    "Proprietary License",
    "WTFPL",
    "Public Domain",
    "Creative Commons",
    "Unlicense",
    "DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE",
    "Artistic License 2.0",
    "Mozilla Public License",
    "GPL-3.0",
    "GNU General Public License v3",
    "LGPL-2.1",
    "AGPL-3.0",
    "Eclipse Public License",
    "European Union Public License",
    "zlib License",
    "",
    "   ",
    "\n\n\n",
]


@pytest.mark.parametrize("filename", LICENSE_FILENAMES)
@pytest.mark.parametrize("content", _no_license_texts[:8],
                         ids=[f"nolic-{i}" for i in range(8)])
def test_license_file_unrecognized(tmp_path, filename, content):
    if content.strip():
        _write_license(tmp_path, filename, content)
    assert check_license(tmp_path) is None


def test_empty_repo(tmp_path):
    assert check_license(tmp_path) is None


def test_no_files_at_all(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    assert check_license(tmp_path) is None


def test_pyproject_no_project_section(tmp_path):
    _write_pyproject(tmp_path, """\
        [build-system]
        requires = ["setuptools"]
    """)
    assert check_license(tmp_path) is None


def test_pyproject_no_license_field(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        version = "1.0"
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_empty_string(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = ""
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_empty_dict(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = {}
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_dict_empty_text(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        [project.license]
        text = ""
    """)
    assert check_license(tmp_path) is None


def test_pyproject_classifiers_empty_list(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = []
    """)
    assert check_license(tmp_path) is None


def test_pyproject_classifiers_no_license_ones(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = [
            "Programming Language :: Python :: 3",
            "Development Status :: 4 - Beta",
            "Intended Audience :: Developers",
        ]
    """)
    assert check_license(tmp_path) is None


_no_license_cls_cases = [
    "Programming Language :: Python :: 3",
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Topic :: Software Development",
    "Operating System :: OS Independent",
    "Framework :: Django",
    "Framework :: Flask",
    "Natural Language :: English",
    "Environment :: Console",
    "Topic :: Scientific/Engineering",
]


@pytest.mark.parametrize("cls", _no_license_cls_cases,
                         ids=[f"no-lic-cls-{i}" for i in range(len(_no_license_cls_cases))])
def test_pyproject_classifier_without_license_keyword(tmp_path, cls):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        classifiers = ["{cls}"]
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_unrecognized_name(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = "WTFPL"
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_gpl(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = "GPL-3.0"
    """)
    assert check_license(tmp_path) is None


def test_pyproject_license_dict_unrecognized(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        [project.license]
        text = "LGPL-2.1"
    """)
    assert check_license(tmp_path) is None


def test_license_file_wrong_name(tmp_path):
    (tmp_path / "license.rst").write_text("MIT License")
    assert check_license(tmp_path) is None


def test_license_file_in_subdirectory(tmp_path):
    sub = tmp_path / "docs"
    sub.mkdir()
    (sub / "LICENSE").write_text("MIT License")
    assert check_license(tmp_path) is None


# ============================================================
# 5. Priority / edge cases  (~150 cases)
# ============================================================

# --- LICENSE file wins over pyproject.toml ---
_priority_cases = []
for fname in LICENSE_FILENAMES:
    for file_text, file_expected in [
        ("MIT License", "MIT"),
        ("Apache License, Version 2.0", "Apache-2.0"),
        ("BSD 3-Clause", "BSD-3-Clause"),
        ("ISC License", "ISC"),
    ]:
        for toml_lic in ["Apache-2.0", "BSD-3-Clause", "ISC", "MIT"]:
            if toml_lic != file_expected:
                _priority_cases.append((fname, file_text, file_expected, toml_lic))


@pytest.mark.parametrize("filename, file_content, expected, toml_lic", _priority_cases[:80],
                         ids=[f"prio-{e}-{fn}-{i}" for i, (fn, _, e, _) in enumerate(_priority_cases[:80])])
def test_license_file_overrides_pyproject(tmp_path, filename, file_content, expected, toml_lic):
    _write_license(tmp_path, filename, file_content)
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{toml_lic}"
    """)
    assert check_license(tmp_path) == expected


# --- LICENSE file wins over pyproject classifiers ---
_priority_cls_cases = []
for fname in ["LICENSE", "LICENSE.md", "LICENCE", "COPYING"]:
    for file_text, file_expected in [
        ("MIT License", "MIT"),
        ("BSD 2-Clause", "BSD-2-Clause"),
        ("ISC License", "ISC"),
    ]:
        for cls in [
            "License :: OSI Approved :: Apache Software License 2.0",
            "License :: OSI Approved :: BSD 3-Clause License",
        ]:
            _priority_cls_cases.append((fname, file_text, file_expected, cls))


@pytest.mark.parametrize("filename, file_content, expected, classifier", _priority_cls_cases,
                         ids=[f"prio-cls-{e}-{fn}-{i}" for i, (fn, _, e, _) in enumerate(_priority_cls_cases)])
def test_license_file_overrides_classifier(tmp_path, filename, file_content, expected, classifier):
    _write_license(tmp_path, filename, file_content)
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        classifiers = ["{classifier}"]
    """)
    assert check_license(tmp_path) == expected


# --- First filename match wins ---
def test_license_before_licence(tmp_path):
    _write_license(tmp_path, "LICENSE", "MIT License")
    _write_license(tmp_path, "LICENCE", "Apache License, Version 2.0")
    assert check_license(tmp_path) == "MIT"


def test_license_before_copying(tmp_path):
    _write_license(tmp_path, "LICENSE", "BSD 3-Clause")
    _write_license(tmp_path, "COPYING", "MIT License")
    assert check_license(tmp_path) == "BSD-3-Clause"


def test_licence_txt_before_copying(tmp_path):
    _write_license(tmp_path, "LICENCE.txt", "ISC License")
    _write_license(tmp_path, "COPYING", "MIT License")
    assert check_license(tmp_path) == "ISC"


def test_license_md_before_licence(tmp_path):
    _write_license(tmp_path, "LICENSE.md", "Apache License, Version 2.0")
    _write_license(tmp_path, "LICENCE", "MIT License")
    assert check_license(tmp_path) == "Apache-2.0"


# --- First pattern match wins (order in _LICENSE_PATTERNS) ---
def test_mit_wins_over_mit0_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "MIT License and also MIT-0")
    assert check_license(tmp_path) == "MIT"


def test_mit_before_apache_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "MIT License\nApache License, Version 2.0")
    assert check_license(tmp_path) == "MIT"


def test_mit_before_bsd_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "MIT License\nBSD 3-Clause")
    assert check_license(tmp_path) == "MIT"


def test_apache_before_bsd_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "Apache License, Version 2.0\nBSD 3-Clause")
    assert check_license(tmp_path) == "Apache-2.0"


def test_bsd3_before_bsd2_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "BSD 3-Clause\nBSD 2-Clause")
    assert check_license(tmp_path) == "BSD-3-Clause"


def test_bsd2_before_isc_in_file(tmp_path):
    _write_license(tmp_path, "LICENSE", "BSD 2-Clause\nISC License")
    assert check_license(tmp_path) == "BSD-2-Clause"


# --- pyproject license field checked before classifiers ---
def test_pyproject_license_field_before_classifiers(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = "MIT"
        classifiers = ["License :: OSI Approved :: Apache Software License 2.0"]
    """)
    assert check_license(tmp_path) == "MIT"


def test_pyproject_license_field_before_classifiers_2(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = "Apache-2.0"
        classifiers = ["License :: OSI Approved :: MIT License"]
    """)
    assert check_license(tmp_path) == "Apache-2.0"


def test_pyproject_license_field_before_classifiers_3(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        license = "BSD-3-Clause"
        classifiers = ["License :: ISC"]
    """)
    assert check_license(tmp_path) == "BSD-3-Clause"


# --- pyproject.toml license dict "text" preferred over "expression" ---
def test_pyproject_text_preferred_over_expression(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        [project.license]
        text = "MIT"
        expression = "Apache-2.0"
    """)
    assert check_license(tmp_path) == "MIT"


def test_pyproject_text_empty_falls_to_expression(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        [project.license]
        text = ""
        expression = "Apache-2.0"
    """)
    assert check_license(tmp_path) == "Apache-2.0"


# --- Pattern match order in pyproject license field ---
_pyproject_order_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    _pyproject_order_cases.append((lic, lic))
# MIT-0 as license field → MIT
_pyproject_order_cases.append(("MIT-0", "MIT"))

for combo_val, expected in [
    ("MIT and Apache-2.0", "MIT"),
    ("Apache-2.0 or MIT", "MIT"),
    ("MIT OR BSD-3-Clause", "MIT"),
    ("BSD-3-Clause OR BSD-2-Clause", "BSD-3-Clause"),
    ("BSD-2-Clause AND ISC", "BSD-2-Clause"),
    ("ISC or MIT", "MIT"),
    ("Apache-2.0 AND BSD-3-Clause", "Apache-2.0"),
]:
    _pyproject_order_cases.append((combo_val, expected))


@pytest.mark.parametrize("lic_val, expected", _pyproject_order_cases,
                         ids=[f"toml-order-{e}-{i}" for i, (_, e) in enumerate(_pyproject_order_cases)])
def test_pyproject_license_pattern_order(tmp_path, lic_val, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{lic_val}"
    """)
    assert check_license(tmp_path) == expected


# --- Classifier: MIT vs MIT-0 distinction ---
def test_classifier_mit_not_mit0(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: MIT License"]
    """)
    assert check_license(tmp_path) == "MIT"


def test_classifier_mit0_explicit(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: MIT-0 License"]
    """)
    assert check_license(tmp_path) == "MIT-0"


def test_classifier_no_attribution_without_mit(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: No Attribution License"]
    """)
    assert check_license(tmp_path) == "MIT-0"


def test_classifier_mit_no_attribution_has_mit(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: MIT No Attribution License"]
    """)
    assert check_license(tmp_path) == "MIT"


# --- Classifier: BSD 3 vs 2 distinction ---
def test_classifier_bsd_with_3(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: BSD License (3-Clause)"]
    """)
    assert check_license(tmp_path) == "BSD-3-Clause"


def test_classifier_bsd_with_2(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: BSD License (2-Clause)"]
    """)
    assert check_license(tmp_path) == "BSD-2-Clause"


def test_classifier_bsd_with_3_and_2(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = ["License :: OSI Approved :: BSD 3-Clause and 2-Clause"]
    """)
    assert check_license(tmp_path) == "BSD-3-Clause"


# --- First classifier with "License" wins ---
def test_first_license_classifier_wins(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = [
            "License :: OSI Approved :: Apache Software License 2.0",
            "License :: OSI Approved :: MIT License",
        ]
    """)
    assert check_license(tmp_path) == "Apache-2.0"


def test_first_license_classifier_wins_2(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = [
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: Apache Software License 2.0",
        ]
    """)
    assert check_license(tmp_path) == "MIT"


def test_first_license_classifier_wins_isc_then_mit(tmp_path):
    _write_pyproject(tmp_path, """\
        [project]
        name = "foo"
        classifiers = [
            "License :: ISC License",
            "License :: OSI Approved :: MIT License",
        ]
    """)
    assert check_license(tmp_path) == "ISC"


# --- Edge: unrecognized license file content, falls through to pyproject ---
_fallthrough_cases = []
for lic in _LICENSE_NAMES_NO_MIT0:
    _fallthrough_cases.append(("Proprietary License", lic, lic))
    _fallthrough_cases.append(("GPL-3.0 License", lic, lic))
    _fallthrough_cases.append(("Unknown License Text", lic, lic))
# MIT-0 in pyproject field → MIT
_fallthrough_cases.append(("Proprietary License", "MIT-0", "MIT"))
_fallthrough_cases.append(("GPL-3.0 License", "MIT-0", "MIT"))
_fallthrough_cases.append(("Unknown License Text", "MIT-0", "MIT"))


@pytest.mark.parametrize("file_text, toml_lic, expected", _fallthrough_cases,
                         ids=[f"fallthrough-{e}-{i}" for i, (_, _, e) in enumerate(_fallthrough_cases)])
def test_unrecognized_file_falls_to_pyproject(tmp_path, file_text, toml_lic, expected):
    _write_license(tmp_path, "LICENSE", file_text)
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{toml_lic}"
    """)
    assert check_license(tmp_path) == expected


# --- Edge: empty license file, falls through to pyproject ---
_empty_file_fallthrough = []
for fname in LICENSE_FILENAMES:
    for lic in _LICENSE_NAMES_NO_MIT0:
        _empty_file_fallthrough.append((fname, lic, lic))
    _empty_file_fallthrough.append((fname, "MIT-0", "MIT"))


@pytest.mark.parametrize("filename, toml_lic, expected", _empty_file_fallthrough,
                         ids=[f"empty-file-{e}-{fn}-{i}" for i, (fn, _, e) in enumerate(_empty_file_fallthrough)])
def test_empty_license_file_falls_to_pyproject(tmp_path, filename, toml_lic, expected):
    _write_license(tmp_path, filename, "")
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{toml_lic}"
    """)
    assert check_license(tmp_path) == expected


# --- Edge: no license field, falls to classifiers ---
_field_to_cls_cases = []
for cls, expected in _all_classifier_cases:
    _field_to_cls_cases.append((cls, expected))


@pytest.mark.parametrize("classifier, expected", _field_to_cls_cases,
                         ids=[f"field-to-cls-{e}-{i}" for i, (_, e) in enumerate(_field_to_cls_cases)])
def test_no_license_field_falls_to_classifiers(tmp_path, classifier, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        version = "1.0"
        classifiers = ["{classifier}"]
    """)
    assert check_license(tmp_path) == expected


# --- Edge: unrecognized license field falls to classifiers ---
_unrec_field_to_cls = []
for cls, expected in _all_classifier_cases[:12]:
    _unrec_field_to_cls.append(("WTFPL", cls, expected))
    _unrec_field_to_cls.append(("GPL-3.0", cls, expected))


@pytest.mark.parametrize("lic_str, classifier, expected", _unrec_field_to_cls,
                         ids=[f"unrec-field-cls-{e}-{i}" for i, (_, _, e) in enumerate(_unrec_field_to_cls)])
def test_unrecognized_license_field_falls_to_classifiers(tmp_path, lic_str, classifier, expected):
    _write_pyproject(tmp_path, f"""\
        [project]
        name = "foo"
        license = "{lic_str}"
        classifiers = ["{classifier}"]
    """)
    assert check_license(tmp_path) == expected
