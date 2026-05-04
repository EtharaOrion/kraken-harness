import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import _parse_min_python


GE_BASIC = [
    (">=3.8", "3.8"),
    (">=3.9", "3.9"),
    (">=3.10", "3.10"),
    (">=3.11", "3.11"),
    (">=3.12", "3.12"),
    (">=3.13", "3.13"),
    (">=3.7", "3.7"),
    (">=3.6", "3.6"),
    (">=3.5", "3.5"),
    (">=2.7", "2.7"),
    (">=3.0", "3.0"),
    (">=3.14", "3.14"),
    (">=3.99", "3.99"),
    (">=4.0", "4.0"),
    (">=3.8 ", "3.8"),
    (" >=3.8", "3.8"),
    (" >=3.8 ", "3.8"),
]


@pytest.mark.parametrize("spec, expected", GE_BASIC, ids=[f"ge-basic-{i}" for i in range(len(GE_BASIC))])
def test_ge_basic(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GE_WITH_SPACE = [
    (">= 3.8", "3.8"),
    (">= 3.9", "3.9"),
    (">= 3.10", "3.10"),
    (">= 3.11", "3.11"),
    (">= 3.12", "3.12"),
    (">=  3.8", "3.8"),
    (">=   3.9", "3.9"),
    (">= 3.7", "3.7"),
    (">= 3.6", "3.6"),
    (">= 2.7", "2.7"),
]


@pytest.mark.parametrize("spec, expected", GE_WITH_SPACE, ids=[f"ge-space-{i}" for i in range(len(GE_WITH_SPACE))])
def test_ge_with_space(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GT_BASIC = [
    (">3.7", "3.7"),
    (">3.8", "3.8"),
    (">3.9", "3.9"),
    (">3.10", "3.10"),
    (">3.11", "3.11"),
    (">3.6", "3.6"),
    (">3.5", "3.5"),
    (">2.7", "2.7"),
    (">3.0", "3.0"),
    (">4.0", "4.0"),
]


@pytest.mark.parametrize("spec, expected", GT_BASIC, ids=[f"gt-basic-{i}" for i in range(len(GT_BASIC))])
def test_gt_basic(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GT_WITH_SPACE = [
    ("> 3.7", "3.7"),
    ("> 3.8", "3.8"),
    ("> 3.9", "3.9"),
    ("> 3.10", "3.10"),
    ("> 3.11", "3.11"),
    (">  3.7", "3.7"),
    (">  3.8", "3.8"),
    (">   3.9", "3.9"),
    ("> 3.6", "3.6"),
    ("> 2.7", "2.7"),
]


@pytest.mark.parametrize("spec, expected", GT_WITH_SPACE, ids=[f"gt-space-{i}" for i in range(len(GT_WITH_SPACE))])
def test_gt_with_space(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GE_COMPOUND = [
    (">=3.8,<3.12", "3.8"),
    (">=3.9,<3.13", "3.9"),
    (">=3.7,<3.11", "3.7"),
    (">=3.8,<=3.12", "3.8"),
    (">=3.8,!=3.9", "3.8"),
    (">=3.8,<3.12,!=3.9.1", "3.8"),
    (">=3.8, <3.12", "3.8"),
    (">=3.8 ,<3.12", "3.8"),
    (">=3.8 , <3.12", "3.8"),
    (">=3.10,<3.13", "3.10"),
    (">=3.11,<4.0", "3.11"),
    (">=3.6,<3.10", "3.6"),
    (">=3.8,<3.11,!=3.9.0", "3.8"),
    (">=3.8,<3.13,!=3.10.0", "3.8"),
    (">=3.7,!=3.7.0,!=3.7.1", "3.7"),
]


@pytest.mark.parametrize("spec, expected", GE_COMPOUND, ids=[f"ge-compound-{i}" for i in range(len(GE_COMPOUND))])
def test_ge_compound(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GT_COMPOUND = [
    (">3.7,<3.12", "3.7"),
    (">3.8,<3.13", "3.8"),
    (">3.6,<3.10", "3.6"),
    (">3.7,<=3.11", "3.7"),
    (">3.7,!=3.8", "3.7"),
    (">3.9, <3.13", "3.9"),
    (">3.10,<4.0", "3.10"),
    (">3.5,<3.9", "3.5"),
    (">2.7,<3.0", "2.7"),
    (">3.7,<3.12,!=3.9.0", "3.7"),
]


@pytest.mark.parametrize("spec, expected", GT_COMPOUND, ids=[f"gt-compound-{i}" for i in range(len(GT_COMPOUND))])
def test_gt_compound(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


EQ_BASIC = [
    ("==3.8", "3.8"),
    ("==3.9", "3.9"),
    ("==3.10", "3.10"),
    ("==3.11", "3.11"),
    ("==3.12", "3.12"),
    ("==3.7", "3.7"),
    ("==3.6", "3.6"),
    ("==2.7", "2.7"),
    ("==3.0", "3.0"),
    ("==4.0", "4.0"),
]


@pytest.mark.parametrize("spec, expected", EQ_BASIC, ids=[f"eq-basic-{i}" for i in range(len(EQ_BASIC))])
def test_eq_basic(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


EQ_WITH_SPACE = [
    ("== 3.8", "3.8"),
    ("== 3.9", "3.9"),
    ("== 3.10", "3.10"),
    ("== 3.11", "3.11"),
    ("==  3.8", "3.8"),
    ("==   3.9", "3.9"),
    ("== 3.7", "3.7"),
    ("== 3.6", "3.6"),
    ("== 2.7", "2.7"),
    ("== 3.0", "3.0"),
]


@pytest.mark.parametrize("spec, expected", EQ_WITH_SPACE, ids=[f"eq-space-{i}" for i in range(len(EQ_WITH_SPACE))])
def test_eq_with_space(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


FALLBACK = [
    ("", "3.10"),
    ("   ", "3.10"),
    ("~=3.8", "3.10"),
    ("~=3.9", "3.10"),
    ("~=3.10", "3.10"),
    ("!=3.8", "3.10"),
    ("!=3.9", "3.10"),
    ("<3.12", "3.10"),
    ("<3.13", "3.10"),
    ("<=3.12", "3.10"),
    ("<=3.11", "3.10"),
    ("abc", "3.10"),
    ("python", "3.10"),
    ("3.8", "3.10"),
    ("three point eight", "3.10"),
    ("!@#$%^", "3.10"),
    ("null", "3.10"),
    ("None", "3.10"),
    ("===3.8", "3.8"),
    (">> 3.8", "3.8"),
    ("<= 3.8, != 3.7", "3.10"),
    ("~= 3.9", "3.10"),
    ("3", "3.10"),
    ("3.8.1", "3.10"),
    (".8", "3.10"),
    ("random garbage text", "3.10"),
    ("version 3.8", "3.10"),
    ("py38", "3.10"),
    ("cpython-38", "3.10"),
    ("python3.8", "3.10"),
]


@pytest.mark.parametrize("spec, expected", FALLBACK, ids=[f"fallback-{i}" for i in range(len(FALLBACK))])
def test_fallback(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GE_PRIORITY_OVER_EQ = [
    (">=3.8,==3.11", "3.8"),
    ("==3.11,>=3.8", "3.8"),
    (">=3.9,==3.9", "3.9"),
    ("==3.10,>=3.10", "3.10"),
    (">=3.7,==3.12", "3.7"),
    (">3.7,==3.12", "3.7"),
    ("==3.12,>3.7", "3.7"),
    (">3.8,==3.11", "3.8"),
    (">=3.6,==3.8,<3.12", "3.6"),
    ("==3.11,>=3.9,<3.13", "3.9"),
]


@pytest.mark.parametrize("spec, expected", GE_PRIORITY_OVER_EQ, ids=[f"ge-prio-{i}" for i in range(len(GE_PRIORITY_OVER_EQ))])
def test_ge_priority_over_eq(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


REAL_WORLD = [
    (">=3.8", "3.8"),
    (">=3.9", "3.9"),
    (">=3.10", "3.10"),
    (">=3.11", "3.11"),
    (">=3.8,<3.12", "3.8"),
    (">=3.9,<3.13", "3.9"),
    (">=3.8,<3.13", "3.8"),
    (">=3.7,<3.11", "3.7"),
    (">=3.10,<4.0", "3.10"),
    (">= 3.8", "3.8"),
    (">= 3.9", "3.9"),
    (">= 3.10", "3.10"),
    (">=3.8,!=3.9.0,<3.13", "3.8"),
    (">=3.7", "3.7"),
    (">=3.6", "3.6"),
]


@pytest.mark.parametrize("spec, expected", REAL_WORLD, ids=[f"realworld-{i}" for i in range(len(REAL_WORLD))])
def test_real_world(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


EDGE_REGEX = [
    ("x>=3.8", "3.8"),
    ("requires-python>=3.8", "3.8"),
    ("python>=3.8", "3.8"),
    ("python_requires='>=3.8'", "3.8"),
    ("'>=3.9'", "3.9"),
    ('">=3.10"', "3.10"),
    ("(>=3.8)", "3.8"),
    ("[>=3.8]", "3.8"),
    ("prefix>=3.8suffix", "3.8"),
    ("version>=3.8.0", "3.8"),
]


@pytest.mark.parametrize("spec, expected", EDGE_REGEX, ids=[f"edge-regex-{i}" for i in range(len(EDGE_REGEX))])
def test_edge_regex_matching(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


GE_PATCH_VERSIONS = [
    (">=3.8.0", "3.8"),
    (">=3.8.1", "3.8"),
    (">=3.9.0", "3.9"),
    (">=3.9.7", "3.9"),
    (">=3.10.0", "3.10"),
    (">=3.10.12", "3.10"),
    (">=3.11.0", "3.11"),
    (">=3.11.5", "3.11"),
    (">=3.12.0", "3.12"),
    (">3.7.0", "3.7"),
    (">3.8.1", "3.8"),
    (">3.9.2", "3.9"),
    (">3.10.5", "3.10"),
    ("> 3.8.0", "3.8"),
    (">= 3.9.1", "3.9"),
]


@pytest.mark.parametrize("spec, expected", GE_PATCH_VERSIONS, ids=[f"ge-patch-{i}" for i in range(len(GE_PATCH_VERSIONS))])
def test_ge_patch_versions(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


MIXED_OPERATORS = [
    (">=3.8,<3.12,!=3.9.0,!=3.9.1,!=3.10.0", "3.8"),
    (">=3.7,!=3.7.0,!=3.7.1,!=3.7.2,<3.11", "3.7"),
    (">=3.9,<3.13,!=3.10.0", "3.9"),
    (">=3.10,!=3.10.0,!=3.10.1", "3.10"),
    (">3.7,!=3.8.0,<3.12", "3.7"),
    (">=3.8,<3.11,!=3.9.7", "3.8"),
    (">=3.6,!=3.6.0,!=3.6.1,<3.10", "3.6"),
    (">=3.8,>=3.9", "3.8"),
    (">3.7,>=3.8", "3.7"),
    (">=3.8,>3.9", "3.8"),
]


@pytest.mark.parametrize("spec, expected", MIXED_OPERATORS, ids=[f"mixed-{i}" for i in range(len(MIXED_OPERATORS))])
def test_mixed_operators(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


WHITESPACE_EDGE = [
    ("  >=3.8  ", "3.8"),
    ("\t>=3.9", "3.9"),
    ("\n>=3.10\n", "3.10"),
    (">=  3.8", "3.8"),
    (">  3.7", "3.7"),
    ("==  3.11", "3.11"),
    (">=\t3.8", "3.8"),
    (" >= 3.9 ", "3.9"),
    ("  >  3.7  ", "3.7"),
    (" == 3.10 ", "3.10"),
]


@pytest.mark.parametrize("spec, expected", WHITESPACE_EDGE, ids=[f"ws-edge-{i}" for i in range(len(WHITESPACE_EDGE))])
def test_whitespace_edge(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected


NO_MATCH_OPERATORS = [
    ("~=3.8", "3.10"),
    ("~=3.9", "3.10"),
    ("~=3.10", "3.10"),
    ("!=3.8", "3.10"),
    ("!=3.9", "3.10"),
    ("<3.12", "3.10"),
    ("<=3.12", "3.10"),
    ("<= 3.8", "3.10"),
    ("~= 3.9", "3.10"),
    ("!= 3.8", "3.10"),
    ("< 3.12", "3.10"),
    ("<= 3.11", "3.10"),
]


@pytest.mark.parametrize("spec, expected", NO_MATCH_OPERATORS, ids=[f"noop-{i}" for i in range(len(NO_MATCH_OPERATORS))])
def test_no_match_operators(spec: str, expected: str) -> None:
    assert _parse_min_python(spec) == expected
