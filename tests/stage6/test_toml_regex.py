import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import _parse_toml_regex


def _write(tmp_path: Path, text: str, name: str = "pyproject.toml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestFileLevel:

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(tmp_path / "missing.toml") is None

    def test_empty_file(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(_write(tmp_path, "")) is None

    def test_whitespace_only(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(_write(tmp_path, "   \n\n  ")) is None

    def test_comment_only(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(_write(tmp_path, "# just a comment\n")) is None

    def test_unrelated_content(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(_write(tmp_path, "foo = 42\nbar = true\n")) is None

    def test_directory_path(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        assert _parse_toml_regex(d) is None

    def test_only_irrelevant_sections(self, tmp_path: Path) -> None:
        assert _parse_toml_regex(_write(tmp_path, "[tool.black]\nline-length = 88\n")) is None


REQUIRES_PYTHON_CASES = [
    ('requires-python = ">=3.6"', '>=3.6'),
    ('requires-python = ">=3.7"', '>=3.7'),
    ('requires-python = ">=3.8"', '>=3.8'),
    ('requires-python = ">=3.9"', '>=3.9'),
    ('requires-python = ">=3.10"', '>=3.10'),
    ('requires-python = ">=3.11"', '>=3.11'),
    ('requires-python = ">=3.12"', '>=3.12'),
    ('requires-python = ">=3.13"', '>=3.13'),
    ('requires-python = ">3.7"', '>3.7'),
    ('requires-python = ">3.8"', '>3.8'),
    ('requires-python = "==3.8"', '==3.8'),
    ('requires-python = "==3.10"', '==3.10'),
    ('requires-python = "==3.11"', '==3.11'),
    ('requires-python = ">=3.8,<3.12"', '>=3.8,<3.12'),
    ('requires-python = ">=3.9,<3.13"', '>=3.9,<3.13'),
    ('requires-python = ">=3.8,<3.13"', '>=3.8,<3.13'),
    ('requires-python = ">=3.7,<3.11"', '>=3.7,<3.11'),
    ('requires-python = ">=3.8,!=3.9.0"', '>=3.8,!=3.9.0'),
    ('requires-python = "~=3.8"', '~=3.8'),
    ('requires-python = "<3.12"', '<3.12'),
    ('requires-python  =  ">=3.8"', '>=3.8'),
    ('requires-python= ">=3.8"', '>=3.8'),
    ('requires-python =">=3.8"', '>=3.8'),
    ('requires-python  =  ">=3.9"', '>=3.9'),
    ('requires-python= ">=3.9"', '>=3.9'),
    ('requires-python =">=3.9"', '>=3.9'),
    ('[project]\nname = "foo"\nrequires-python = ">=3.8"', '>=3.8'),
    ('[project]\nname = "foo"\nrequires-python = ">=3.9"', '>=3.9'),
    ('[project]\nname = "foo"\nrequires-python = ">=3.10"', '>=3.10'),
    ('[project]\nname = "foo"\nrequires-python = ">=3.11"', '>=3.11'),
    ('[project]\nname = "foo"\nrequires-python = ">=3.12"', '>=3.12'),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.8"\n\n[tool.black]\nline-length = 88', '>=3.8'),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.9"\n\n[tool.black]\nline-length = 88', '>=3.9'),
    ('requires-python = ">=2.7"', '>=2.7'),
    ('requires-python = ">=3.0"', '>=3.0'),
    ('requires-python = ">=3.14"', '>=3.14'),
    ('requires-python = ">=4.0"', '>=4.0'),
    ('requires-python = ">=3.8,<3.12,!=3.9.0,!=3.9.1"', '>=3.8,<3.12,!=3.9.0,!=3.9.1'),
    ('requires-python = ">=3.7,!=3.7.0,!=3.7.1,<3.11"', '>=3.7,!=3.7.0,!=3.7.1,<3.11'),
    ('requires-python = ""', ''),
]


@pytest.mark.parametrize("toml_text, expected", REQUIRES_PYTHON_CASES,
    ids=[f"rp-{i}" for i in range(40)])
def test_requires_python(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["requires-python"] == expected


REQUIRES_PYTHON_NO_MATCH = [
    "requires-python = '>=3.8'",
    'requires_python = ">=3.8"',
    'Requires-Python = ">=3.8"',
    'REQUIRES-PYTHON = ">=3.8"',
]


@pytest.mark.parametrize("toml_text", REQUIRES_PYTHON_NO_MATCH,
    ids=[f"rp-nomatch-{i}" for i in range(4)])
def test_requires_python_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "project" not in result or "requires-python" not in result.get("project", {})


VERSION_CASES = [
    ('version = "0.1.0"', '0.1.0'),
    ('version = "1.0.0"', '1.0.0'),
    ('version = "1.2.3"', '1.2.3'),
    ('version = "2.0.0"', '2.0.0'),
    ('version = "0.0.1"', '0.0.1'),
    ('version = "10.20.30"', '10.20.30'),
    ('version = "1.0.0a1"', '1.0.0a1'),
    ('version = "1.0.0b2"', '1.0.0b2'),
    ('version = "1.0.0rc1"', '1.0.0rc1'),
    ('version = "1.0.0.dev1"', '1.0.0.dev1'),
    ('version = "0.1"', '0.1'),
    ('version = "1.0"', '1.0'),
    ('version = "2.0"', '2.0'),
    ('version = "3.0.0.0"', '3.0.0.0'),
    ('version = "22.3.0"', '22.3.0'),
    ('version = "2024.1.0"', '2024.1.0'),
    ('  version = "0.1.0"', '0.1.0'),
    ('\tversion = "0.1.0"', '0.1.0'),
    ('  version = "1.0.0"', '1.0.0'),
    ('\tversion = "1.0.0"', '1.0.0'),
    ('  version = "2.0.0"', '2.0.0'),
    ('\tversion = "2.0.0"', '2.0.0'),
    ('[project]\nname = "foo"\nversion = "1.0.0"', '1.0.0'),
    ('[project]\nname = "foo"\nversion = "2.3.4"', '2.3.4'),
    ('[project]\nname = "foo"\nversion = "0.1.0"', '0.1.0'),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nversion = "1.0.0"\nname = "bar"', '1.0.0'),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nversion = "2.0.0"\nname = "bar"', '2.0.0'),
    ('version  =  "1.0.0"', '1.0.0'),
    ('version ="1.0.0"', '1.0.0'),
    ('version= "1.0.0"', '1.0.0'),
    ('version  =  "2.0.0"', '2.0.0'),
    ('version ="2.0.0"', '2.0.0'),
    ('version= "2.0.0"', '2.0.0'),
    ('version = ""', ''),
]


@pytest.mark.parametrize("toml_text, expected", VERSION_CASES,
    ids=[f"ver-{i}" for i in range(34)])
def test_version(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["version"] == expected


VERSION_NO_MATCH = [
    '# version = "1.0.0"',
    'xversion = "1.0.0"',
    'tool-version = "1.0.0"',
    'min_version = "1.0.0"',
]


@pytest.mark.parametrize("toml_text", VERSION_NO_MATCH,
    ids=[f"ver-nomatch-{i}" for i in range(4)])
def test_version_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "project" not in result or "version" not in result.get("project", {})


BUILD_SYSTEM_CASES = [
    ('[build-system]\nrequires = ["setuptools"]', ['setuptools']),
    ('[build-system]\nrequires = ["wheel"]', ['wheel']),
    ('[build-system]\nrequires = ["flit_core>=3.2"]', ['flit_core>=3.2']),
    ('[build-system]\nrequires = ["hatchling"]', ['hatchling']),
    ('[build-system]\nrequires = ["poetry-core>=1.0.0"]', ['poetry-core>=1.0.0']),
    ('[build-system]\nrequires = ["setuptools>=42"]', ['setuptools>=42']),
    ('[build-system]\nrequires = ["setuptools>=61.0"]', ['setuptools>=61.0']),
    ('[build-system]\nrequires = ["meson-python>=0.12.1"]', ['meson-python>=0.12.1']),
    ('[build-system]\nrequires = ["cython>=0.29.30"]', ['cython>=0.29.30']),
    ('[build-system]\nrequires = ["numpy>=1.20"]', ['numpy>=1.20']),
    ('[build-system]\nrequires = ["setuptools", "wheel"]', ['setuptools', 'wheel']),
    ('[build-system]\nrequires = ["flit_core>=3.2", "flit_scm"]', ['flit_core>=3.2', 'flit_scm']),
    ('[build-system]\nrequires = ["hatchling", "hatch-vcs"]', ['hatchling', 'hatch-vcs']),
    ('[build-system]\nrequires = ["meson-python>=0.12.1", "cython>=0.29.30"]', ['meson-python>=0.12.1', 'cython>=0.29.30']),
    ('[build-system]\nrequires = ["setuptools", "wheel", "cython"]', ['setuptools', 'wheel', 'cython']),
    ('[build-system]\nrequires = ["setuptools>=42", "wheel", "setuptools-scm"]', ['setuptools>=42', 'wheel', 'setuptools-scm']),
    ('[build-system]\nrequires = ["flit_core>=3.2", "flit_scm", "tomli"]', ['flit_core>=3.2', 'flit_scm', 'tomli']),
    ('[build-system]\nrequires = [\n    "setuptools",\n    "wheel",\n]', ['setuptools', 'wheel']),
    ('[build-system]\nrequires = [\n    "setuptools>=42",\n    "wheel",\n]', ['setuptools>=42', 'wheel']),
    ('[build-system]\nrequires = [\n    "flit_core>=3.2",\n]', ['flit_core>=3.2']),
    ('[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"', ['setuptools']),
    ('[build-system]\nrequires = ["hatchling"]\nbuild-backend = "setuptools.build_meta"', ['hatchling']),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\nbuild-backend = "setuptools.build_meta"', ['flit_core>=3.2']),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "foo"', ['setuptools']),
    ('[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n[project]\nname = "bar"', ['hatchling']),
    ('[build-system]\nrequires  =  ["setuptools"]', ['setuptools']),
    ('[build-system]\nrequires =["setuptools"]', ['setuptools']),
    ('[build-system]\nrequires= ["setuptools"]', ['setuptools']),
    ('[build-system]\nrequires = []', []),
    ('[project]\nname = "foo"\n\n[build-system]\nrequires = ["setuptools"]', ['setuptools']),
    ('[build-system]\nrequires = [\n    "setuptools",\n    # "wheel",\n    "cython",\n]', ['setuptools', 'wheel', 'cython']),
    ('[build-system]\nrequires = ["a", "b", "c", "d"]', ['a', 'b', 'c', 'd']),
    ('[build-system]\nrequires = ["setuptools>=42,<60"]', ['setuptools>=42,<60']),
    ('[build-system]\nrequires = ["numpy>=1.20,<2.0"]', ['numpy>=1.20,<2.0']),
    ('[build-system]\nrequires = ["cython>=0.29.30,!=0.29.33"]', ['cython>=0.29.30,!=0.29.33']),
]


@pytest.mark.parametrize("toml_text, expected", BUILD_SYSTEM_CASES,
    ids=[f"bs-{i}" for i in range(35)])
def test_build_system_requires(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["build-system"]["requires"] == expected


BUILD_SYSTEM_NO_MATCH = [
    'requires = ["setuptools"]',
    '[build]\nrequires = ["setuptools"]',
]


@pytest.mark.parametrize("toml_text", BUILD_SYSTEM_NO_MATCH,
    ids=[f"bs-nomatch-{i}" for i in range(2)])
def test_build_system_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "build-system" not in result or "requires" not in result.get("build-system", {})


PYTEST_INI_CASES = [
    '[tool.pytest.ini_options]',
    '[tool.pytest.ini_options]\naddopts = "-v"',
    '[tool.pytest.ini_options]\ntestpaths = ["tests"]',
    '[tool.pytest.ini_options]\nminversion = "6.0"',
    '[tool.pytest.ini_options]\naddopts = "-v"\ntestpaths = ["tests"]',
    '[tool.pytest.ini_options]\nmarkers = ["slow"]',
    '[tool.pytest.ini_options]\nfilterwarnings = ["error"]',
    '[tool.pytest.ini_options]\nlog_cli = true',
    '[tool.pytest.ini_options]\npythonpath = ["src"]',
    '[tool.pytest.ini_options]\ncollect_ignore = ["setup.py"]',
    '[project]\nname = "foo"\n\n[tool.pytest.ini_options]\naddopts = "-v"',
    '[build-system]\nrequires = ["setuptools"]\n\n[tool.pytest.ini_options]',
    '[tool.pytest.ini_options]\n\n[tool.black]\nline-length = 88',
    '[tool.pytest.ini_options]\naddopts = "--tb=short"\n\n[tool.mypy]\nstrict = true',
    '[tool.pytest.ini_options]\naddopts = "-v --tb=short"\ntestpaths = [\n    "tests",\n    "integration",\n]',
    '[tool.pytest.ini_options] ',
    '[tool.pytest.ini_options]\n  addopts = "-v"',
    '[project]\nname = "x"\nversion = "1.0"\n\n[build-system]\nrequires = ["setuptools"]\n\n[tool.pytest.ini_options]\naddopts = "-v"',
    '[tool.pytest.ini_options]\naddopts = "-v"',
    '[tool.pytest.ini_options]\naddopts = "--strict-markers"',
    '[tool.pytest.ini_options]\naddopts = "-x"',
    '[tool.pytest.ini_options]\naddopts = "--tb=short"',
    '[tool.pytest.ini_options]\naddopts = "--cov=src"',
    '[tool.pytest.ini_options]\naddopts = "-ra"',
]


@pytest.mark.parametrize("toml_text", PYTEST_INI_CASES,
    ids=[f"pytest-ini-{i}" for i in range(24)])
def test_pytest_ini_options(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["tool"]["pytest"]["ini_options"] == {}


PYTEST_INI_NO_MATCH = [
    '[tool.pytest]',
    '[tool.pytest.ini]',
    '[tool.pytest.options]',
    '[tool.pytest.ini_options',
    'tool.pytest.ini_options]',
    '[pytest]\naddopts = "-v"',
]


@pytest.mark.parametrize("toml_text", PYTEST_INI_NO_MATCH,
    ids=[f"pytest-nomatch-{i}" for i in range(6)])
def test_pytest_ini_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "tool" not in result or "pytest" not in result.get("tool", {})


DEPENDENCIES_CASES = [
    ('[project]\ndependencies = ["numpy"]', ['numpy']),
    ('[project]\ndependencies = ["pandas"]', ['pandas']),
    ('[project]\ndependencies = ["requests"]', ['requests']),
    ('[project]\ndependencies = ["click"]', ['click']),
    ('[project]\ndependencies = ["flask"]', ['flask']),
    ('[project]\ndependencies = ["django"]', ['django']),
    ('[project]\ndependencies = ["scipy"]', ['scipy']),
    ('[project]\ndependencies = ["matplotlib"]', ['matplotlib']),
    ('[project]\ndependencies = ["pyyaml"]', ['pyyaml']),
    ('[project]\ndependencies = ["tomli"]', ['tomli']),
    ('[project]\ndependencies = ["packaging"]', ['packaging']),
    ('[project]\ndependencies = ["numpy>=1.20"]', ['numpy>=1.20']),
    ('[project]\ndependencies = ["pandas>=1.3"]', ['pandas>=1.3']),
    ('[project]\ndependencies = ["requests>=2.25"]', ['requests>=2.25']),
    ('[project]\ndependencies = ["click>=8.0"]', ['click>=8.0']),
    ('[project]\ndependencies = ["flask>=2.0"]', ['flask>=2.0']),
    ('[project]\ndependencies = ["django>=4.0"]', ['django>=4.0']),
    ('[project]\ndependencies = ["numpy", "scipy"]', ['numpy', 'scipy']),
    ('[project]\ndependencies = ["requests", "click"]', ['requests', 'click']),
    ('[project]\ndependencies = ["pandas", "numpy>=1.20"]', ['pandas', 'numpy>=1.20']),
    ('[project]\ndependencies = ["flask", "jinja2"]', ['flask', 'jinja2']),
    ('[project]\ndependencies = ["django", "djangorestframework"]', ['django', 'djangorestframework']),
    ('[project]\ndependencies = ["numpy", "scipy", "matplotlib"]', ['numpy', 'scipy', 'matplotlib']),
    ('[project]\ndependencies = ["requests", "click", "rich"]', ['requests', 'click', 'rich']),
    ('[project]\ndependencies = [\n    "numpy",\n    "scipy",\n]', ['numpy', 'scipy']),
    ('[project]\ndependencies = [\n    "requests>=2.25",\n    "click>=8.0",\n    "rich>=10.0",\n]', ['requests>=2.25', 'click>=8.0', 'rich>=10.0']),
    ('[project]\ndependencies = []', []),
    ('[project]\nname = "foo"\nversion = "1.0.0"\ndependencies = ["numpy"]', ['numpy']),
    ('[project]\nname = "bar"\nrequires-python = ">=3.8"\ndependencies = ["requests", "click"]', ['requests', 'click']),
    ('[project]\ndependencies = ["numpy>=1.20,<2.0"]', ['numpy>=1.20,<2.0']),
    ('[project]\ndependencies = ["scipy>=1.7,!=1.7.2"]', ['scipy>=1.7,!=1.7.2']),
    ('[project]\ndependencies = ["pandas>=1.3,<2.0"]', ['pandas>=1.3,<2.0']),
    ('[project]\ndependencies = ["package-extra1"]', ['package-extra1']),
    ('[project]\ndependencies = ["package-extra1-extra2"]', ['package-extra1-extra2']),
    ('[project]\ndependencies = ["requests-security"]', ['requests-security']),
    ('[project]\ndependencies  =  ["numpy"]', ['numpy']),
    ('[project]\ndependencies =["numpy"]', ['numpy']),
    ('[project]\ndependencies= ["numpy"]', ['numpy']),
]


@pytest.mark.parametrize("toml_text, expected", DEPENDENCIES_CASES,
    ids=[f"dep-{i}" for i in range(38)])
def test_dependencies(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["dependencies"] == expected


DEPENDENCIES_NO_MATCH = [
    'dependencies = ["numpy"]',
    '[project.optional-dependencies]\ndev = ["pytest"]',
]


@pytest.mark.parametrize("toml_text", DEPENDENCIES_NO_MATCH,
    ids=[f"dep-nomatch-{i}" for i in range(2)])
def test_dependencies_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "project" not in result or "dependencies" not in result.get("project", {})


LICENSE_CASES = [
    ('[project]\nlicense = {text = "MIT"}', 'MIT'),
    ('[project]\nlicense = {text = "Apache-2.0"}', 'Apache-2.0'),
    ('[project]\nlicense = {text = "BSD-3-Clause"}', 'BSD-3-Clause'),
    ('[project]\nlicense = {text = "GPL-3.0"}', 'GPL-3.0'),
    ('[project]\nlicense = {text = "LGPL-2.1"}', 'LGPL-2.1'),
    ('[project]\nlicense = {text = "ISC"}', 'ISC'),
    ('[project]\nlicense = {text = "MPL-2.0"}', 'MPL-2.0'),
    ('[project]\nlicense = {text = "Unlicense"}', 'Unlicense'),
    ('[project]\nlicense = {text = "WTFPL"}', 'WTFPL'),
    ('[project]\nlicense = {text = "CC0-1.0"}', 'CC0-1.0'),
    ('[project]\nlicense = {text = "BSD-2-Clause"}', 'BSD-2-Clause'),
    ('[project]\nlicense = {text = "AGPL-3.0"}', 'AGPL-3.0'),
    ('[project]\nlicense = {text = "EPL-2.0"}', 'EPL-2.0'),
    ('[project]\nlicense = {text = "Artistic-2.0"}', 'Artistic-2.0'),
    ('[project]\nlicense = {text = "Zlib"}', 'Zlib'),
    ('[project]\nname = "foo"\nlicense = {text = "MIT"}', 'MIT'),
    ('[project]\nname = "foo"\nversion = "1.0.0"\nlicense = {text = "MIT"}', 'MIT'),
    ('[project]\nname = "foo"\nlicense = {text = "Apache-2.0"}', 'Apache-2.0'),
    ('[project]\nname = "foo"\nversion = "1.0.0"\nlicense = {text = "Apache-2.0"}', 'Apache-2.0'),
    ('[project]\nname = "foo"\nlicense = {text = "BSD-3-Clause"}', 'BSD-3-Clause'),
    ('[project]\nname = "foo"\nversion = "1.0.0"\nlicense = {text = "BSD-3-Clause"}', 'BSD-3-Clause'),
    ('[project]\nlicense = { text = "MIT" }', 'MIT'),
    ('[project]\nlicense = {text = "MIT"}', 'MIT'),
    ('[project]\nlicense = { text="MIT" }', 'MIT'),
    ('[project]\nlicense = {  text  =  "MIT"  }', 'MIT'),
    ('[project]\nlicense = {text = "Apache License, Version 2.0"}', 'Apache License, Version 2.0'),
    ('[project]\nlicense = {text = "The MIT License (MIT)"}', 'The MIT License (MIT)'),
    ('[project]\nlicense = {text = ""}', ''),
]


@pytest.mark.parametrize("toml_text, expected", LICENSE_CASES,
    ids=[f"lic-{i}" for i in range(28)])
def test_license_text(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["license"]["text"] == expected


LICENSE_NO_MATCH = [
    'license = {text = "MIT"}',
    '[project]\nlicense = "MIT"',
    '[project]\nlicense = {file = "LICENSE"}',
]


@pytest.mark.parametrize("toml_text", LICENSE_NO_MATCH,
    ids=[f"lic-nomatch-{i}" for i in range(3)])
def test_license_no_match(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is None or "project" not in result or "license" not in result.get("project", {}) or "text" not in result.get("project", {}).get("license", {})


COMBO_CASES = [
    ('[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"', {'project': {'requires-python': '>=3.8', 'version': '1.0.0'}}),
    ('[project]\nrequires-python = ">=3.9"\nversion = "2.0.0"', {'project': {'requires-python': '>=3.9', 'version': '2.0.0'}}),
    ('[project]\nrequires-python = ">=3.10"\nversion = "0.1.0"', {'project': {'requires-python': '>=3.10', 'version': '0.1.0'}}),
    ('[project]\nrequires-python = ">=3.11"\nversion = "3.0.0"', {'project': {'requires-python': '>=3.11', 'version': '3.0.0'}}),
    ('[project]\nrequires-python = ">=3.12"\nversion = "1.2.3"', {'project': {'requires-python': '>=3.12', 'version': '1.2.3'}}),
    ('[project]\nrequires-python = ">=3.8"\ndependencies = ["numpy"]', {'project': {'requires-python': '>=3.8', 'dependencies': ['numpy']}}),
    ('[project]\nrequires-python = ">=3.9"\ndependencies = ["numpy"]', {'project': {'requires-python': '>=3.9', 'dependencies': ['numpy']}}),
    ('[project]\nrequires-python = ">=3.10"\ndependencies = ["numpy"]', {'project': {'requires-python': '>=3.10', 'dependencies': ['numpy']}}),
    ('[project]\nversion = "1.0.0"\ndependencies = ["requests"]', {'project': {'version': '1.0.0', 'dependencies': ['requests']}}),
    ('[project]\nversion = "2.0.0"\ndependencies = ["requests"]', {'project': {'version': '2.0.0', 'dependencies': ['requests']}}),
    ('[project]\nversion = "0.1.0"\ndependencies = ["requests"]', {'project': {'version': '0.1.0', 'dependencies': ['requests']}}),
    ('[project]\nrequires-python = ">=3.8"\nlicense = {text = "MIT"}', {'project': {'requires-python': '>=3.8', 'license': {'text': 'MIT'}}}),
    ('[project]\nrequires-python = ">=3.9"\nlicense = {text = "MIT"}', {'project': {'requires-python': '>=3.9', 'license': {'text': 'MIT'}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.8"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.8'}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.9"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.9'}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.10"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.10'}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nversion = "1.0.0"', {'build-system': {'requires': ['setuptools']}, 'project': {'version': '1.0.0'}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nversion = "2.0.0"', {'build-system': {'requires': ['setuptools']}, 'project': {'version': '2.0.0'}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools']}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"\ndependencies = ["numpy", "scipy"]', {'project': {'requires-python': '>=3.8', 'version': '1.0.0', 'dependencies': ['numpy', 'scipy']}}),
    ('[project]\nrequires-python = ">=3.9"\nversion = "2.0.0"\ndependencies = ["numpy", "scipy"]', {'project': {'requires-python': '>=3.9', 'version': '2.0.0', 'dependencies': ['numpy', 'scipy']}}),
    ('[project]\nrequires-python = ">=3.10"\nversion = "0.1.0"\ndependencies = ["numpy", "scipy"]', {'project': {'requires-python': '>=3.10', 'version': '0.1.0', 'dependencies': ['numpy', 'scipy']}}),
    ('[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"\nlicense = {text = "MIT"}', {'project': {'requires-python': '>=3.8', 'version': '1.0.0', 'license': {'text': 'MIT'}}}),
    ('[project]\nrequires-python = ">=3.9"\nversion = "2.0.0"\nlicense = {text = "MIT"}', {'project': {'requires-python': '>=3.9', 'version': '2.0.0', 'license': {'text': 'MIT'}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.8"\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.8'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.9"\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.9'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.10"\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.10'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"\nlicense = {text = "MIT"}\ndependencies = ["numpy"]', {'project': {'requires-python': '>=3.8', 'version': '1.0.0', 'dependencies': ['numpy'], 'license': {'text': 'MIT'}}}),
    ('[project]\nrequires-python = ">=3.9"\nversion = "1.0.0"\nlicense = {text = "MIT"}\ndependencies = ["numpy"]', {'project': {'requires-python': '>=3.9', 'version': '1.0.0', 'dependencies': ['numpy'], 'license': {'text': 'MIT'}}}),
    ('[build-system]\nrequires = ["setuptools", "wheel"]\n\n[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"\n\n[tool.pytest.ini_options]', {'build-system': {'requires': ['setuptools', 'wheel']}, 'project': {'requires-python': '>=3.8', 'version': '1.0.0'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools", "wheel"]\n\n[project]\nrequires-python = ">=3.9"\nversion = "1.0.0"\n\n[tool.pytest.ini_options]', {'build-system': {'requires': ['setuptools', 'wheel']}, 'project': {'requires-python': '>=3.9', 'version': '1.0.0'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.8"\nversion = "1.0.0"\nlicense = {text = "MIT"}\ndependencies = ["numpy"]\n\n[tool.pytest.ini_options]', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.8', 'version': '1.0.0', 'dependencies': ['numpy'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nrequires-python = ">=3.9"\nversion = "1.0.0"\nlicense = {text = "MIT"}\ndependencies = ["numpy"]\n\n[tool.pytest.ini_options]', {'build-system': {'requires': ['setuptools']}, 'project': {'requires-python': '>=3.9', 'version': '1.0.0', 'dependencies': ['numpy'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools", "wheel"]\n\n[project]\nname = "mypackage"\nrequires-python = ">=3.8"\nversion = "1.0.0"\nlicense = {text = "MIT"}\ndependencies = ["numpy", "requests"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools', 'wheel']}, 'project': {'requires-python': '>=3.8', 'version': '1.0.0', 'dependencies': ['numpy', 'requests'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nname = "another"\nrequires-python = ">=3.9"\nversion = "2.3.4"\nlicense = {text = "Apache-2.0"}\ndependencies = ["click", "rich"]\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]', {'build-system': {'requires': ['hatchling']}, 'project': {'requires-python': '>=3.9', 'version': '2.3.4', 'dependencies': ['click', 'rich'], 'license': {'text': 'Apache-2.0'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools>=42", "wheel"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "my-package"\nversion = "0.1.0"\nrequires-python = ">=3.8"\nlicense = {text = "MIT"}\ndependencies = [\n    "requests>=2.25",\n    "click>=8.0",\n]\n\n[tool.pytest.ini_options]\naddopts = "-v --tb=short"\ntestpaths = ["tests"]', {'build-system': {'requires': ['setuptools>=42', 'wheel']}, 'project': {'requires-python': '>=3.8', 'version': '0.1.0', 'dependencies': ['requests>=2.25', 'click>=8.0'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\nbuild-backend = "flit_core.buildapi"\n\n[project]\nname = "science-lib"\nversion = "3.0.0"\nrequires-python = ">=3.10"\ndependencies = [\n    "numpy>=1.20",\n    "scipy>=1.7",\n    "matplotlib>=3.5",\n]', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'requires-python': '>=3.10', 'version': '3.0.0', 'dependencies': ['numpy>=1.20', 'scipy>=1.7', 'matplotlib>=3.5']}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\ndependencies = ["numpy"]', {'build-system': {'requires': ['setuptools']}, 'project': {'dependencies': ['numpy']}}),
    ('[project]\nversion = "1.0.0"\nlicense = {text = "BSD-3-Clause"}', {'project': {'version': '1.0.0', 'license': {'text': 'BSD-3-Clause'}}}),
    ('[project]\ndependencies = ["click"]\n\n[tool.pytest.ini_options]', {'project': {'dependencies': ['click']}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nlicense = {text = "MIT"}\ndependencies = ["numpy", "pandas"]', {'project': {'dependencies': ['numpy', 'pandas'], 'license': {'text': 'MIT'}}}),
    ('[project]\nversion = "2.0.0"\n\n[tool.pytest.ini_options]', {'project': {'version': '2.0.0'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools"]\n\n[project]\nlicense = {text = "GPL-3.0"}', {'build-system': {'requires': ['setuptools']}, 'project': {'license': {'text': 'GPL-3.0'}}}),
]


@pytest.mark.parametrize("toml_text, expected", COMBO_CASES,
    ids=[f"combo-{i}" for i in range(43)])
def test_combinations(tmp_path: Path, toml_text: str, expected: dict) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result == expected


class TestEdgeCases:

    def test_unicode_in_version(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\nversion = "1.0.0-beta"'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0-beta"

    def test_version_with_plus(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\nversion = "1.0.0+local"'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0+local"

    def test_version_with_pre(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\nversion = "1.0.0.post1"'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0.post1"

    def test_dep_with_url(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\ndependencies = ["pkg @ https://example.com/pkg.tar.gz"]'))
        assert result is not None
        assert result["project"]["dependencies"] == ["pkg @ https://example.com/pkg.tar.gz"]

    def test_dep_with_semicolon(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\ndependencies = ["tomli>=1.0"]'))
        assert result is not None
        assert result["project"]["dependencies"] == ["tomli>=1.0"]

    def test_large_file(self, tmp_path: Path) -> None:
        content = "[project]\n" + "# comment\n" * 500 + 'requires-python = ">=3.8"\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"

    def test_windows_line_endings(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\r\nrequires-python = ">=3.8"\r\n'))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"

    def test_mixed_line_endings(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\nversion = "1.0.0"\r\nrequires-python = ">=3.8"\n'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0"
        assert result["project"]["requires-python"] == ">=3.8"

    def test_tabs_in_file(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\n\tversion = "1.0.0"\n'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0"

    def test_multiple_project_sections_first_wins(self, tmp_path: Path) -> None:
        content = '[project]\nrequires-python = ">=3.8"\ndependencies = ["numpy"]\n\n[other]\nfoo = 1\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"

    def test_setdefault_merges(self, tmp_path: Path) -> None:
        content = 'requires-python = ">=3.8"\n[project]\nversion = "1.0.0"\ndependencies = ["numpy"]\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"
        assert result["project"]["version"] == "1.0.0"
        assert result["project"]["dependencies"] == ["numpy"]

    def test_version_not_in_middle_of_word(self, tmp_path: Path) -> None:
        content = 'myversion = "1.0.0"\nversion = "2.0.0"\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        # regex matches first ^\\s*version, which is myversion? No, myversion starts line
        # actually the regex is ^\\s*version so "myversion" at ^ would NOT match since "m" != whitespace/version
        assert result["project"]["version"] == "2.0.0"

EDGE_RP = [
    ('requires-python = ">=3.8"', '>=3.8'),
    ('[project]\nrequires-python = ">=3.8"\n[other]\nrequires-python = ">=3.11"', '>=3.8'),
]


@pytest.mark.parametrize("toml_text, expected", EDGE_RP,
    ids=[f"edge-rp-{i}" for i in range(2)])
def test_edge_requires_python(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["requires-python"] == expected


EDGE_BS = [
    ('[build-system]\nrequires = ["setuptools"]\n[project]', ['setuptools']),
    ('[build-system]\nrequires = ["a"]\n[tool]', ['a']),
]


@pytest.mark.parametrize("toml_text, expected", EDGE_BS,
    ids=[f"edge-bs-{i}" for i in range(2)])
def test_edge_build_system(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["build-system"]["requires"] == expected


MORE_RP = [
    ('[project]\nname = "pkg"\nrequires-python = ">=3.8"\nversion = "1.0"', '>=3.8'),
    ('# header comment\n[project]\nrequires-python = ">=3.8"', '>=3.8'),
    ('[project]\nrequires-python = ">=3.8"\n# trailing comment', '>=3.8'),
    ('[project]\nname = "pkg"\nrequires-python = ">=3.9"\nversion = "1.0"', '>=3.9'),
    ('# header comment\n[project]\nrequires-python = ">=3.9"', '>=3.9'),
    ('[project]\nrequires-python = ">=3.9"\n# trailing comment', '>=3.9'),
    ('[project]\nname = "pkg"\nrequires-python = ">=3.10"\nversion = "1.0"', '>=3.10'),
    ('# header comment\n[project]\nrequires-python = ">=3.10"', '>=3.10'),
    ('[project]\nrequires-python = ">=3.10"\n# trailing comment', '>=3.10'),
    ('[project]\nname = "pkg"\nrequires-python = ">=3.11"\nversion = "1.0"', '>=3.11'),
    ('# header comment\n[project]\nrequires-python = ">=3.11"', '>=3.11'),
    ('[project]\nrequires-python = ">=3.11"\n# trailing comment', '>=3.11'),
    ('[project]\nname = "pkg"\nrequires-python = ">=3.12"\nversion = "1.0"', '>=3.12'),
    ('# header comment\n[project]\nrequires-python = ">=3.12"', '>=3.12'),
    ('[project]\nrequires-python = ">=3.12"\n# trailing comment', '>=3.12'),
]


@pytest.mark.parametrize("toml_text, expected", MORE_RP,
    ids=[f"more-rp-{i}" for i in range(15)])
def test_more_requires_python(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["requires-python"] == expected


MORE_VER = [
    ('[project]\nname = "pkg"\nversion = "0.0.1"', '0.0.1'),
    ('[project]\nname = "pkg"\nversion = "0.1.0"', '0.1.0'),
    ('[project]\nname = "pkg"\nversion = "1.0.0"', '1.0.0'),
    ('[project]\nname = "pkg"\nversion = "2.0.0"', '2.0.0'),
    ('[project]\nname = "pkg"\nversion = "3.0.0"', '3.0.0'),
    ('[project]\nname = "pkg"\nversion = "10.0.0"', '10.0.0'),
    ('[project]\nname = "pkg"\nversion = "0.0.0"', '0.0.0'),
    ('[project]\nname = "pkg"\nversion = "99.99.99"', '99.99.99'),
]


@pytest.mark.parametrize("toml_text, expected", MORE_VER,
    ids=[f"more-ver-{i}" for i in range(8)])
def test_more_version(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["version"] == expected


MORE_BS = [
    ('[build-system]\nrequires = ["setuptools"]\nbuild-backend = "x"', ['setuptools']),
    ('[build-system]\nrequires = ["hatchling"]\nbuild-backend = "x"', ['hatchling']),
    ('[build-system]\nrequires = ["flit_core"]\nbuild-backend = "x"', ['flit_core']),
    ('[build-system]\nrequires = ["poetry-core"]\nbuild-backend = "x"', ['poetry-core']),
    ('[build-system]\nrequires = ["meson-python"]\nbuild-backend = "x"', ['meson-python']),
    ('[build-system]\nrequires = ["pdm-backend"]\nbuild-backend = "x"', ['pdm-backend']),
    ('[build-system]\nrequires = ["whey"]\nbuild-backend = "x"', ['whey']),
    ('[build-system]\nrequires = ["sipbuild"]\nbuild-backend = "x"', ['sipbuild']),
    ('[build-system]\nrequires = ["scikit-build-core"]\nbuild-backend = "x"', ['scikit-build-core']),
]


@pytest.mark.parametrize("toml_text, expected", MORE_BS,
    ids=[f"more-bs-{i}" for i in range(9)])
def test_more_build_system(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["build-system"]["requires"] == expected


MORE_DEP = [
    ('[project]\ndependencies = ["numpy"]', ['numpy']),
    ('[project]\ndependencies = ["scipy"]', ['scipy']),
    ('[project]\ndependencies = ["pandas"]', ['pandas']),
    ('[project]\ndependencies = ["matplotlib"]', ['matplotlib']),
    ('[project]\ndependencies = ["seaborn"]', ['seaborn']),
    ('[project]\ndependencies = ["plotly"]', ['plotly']),
    ('[project]\ndependencies = ["requests"]', ['requests']),
    ('[project]\ndependencies = ["httpx"]', ['httpx']),
    ('[project]\ndependencies = ["aiohttp"]', ['aiohttp']),
    ('[project]\ndependencies = ["flask"]', ['flask']),
    ('[project]\ndependencies = ["django"]', ['django']),
    ('[project]\ndependencies = ["fastapi"]', ['fastapi']),
    ('[project]\ndependencies = ["click"]', ['click']),
    ('[project]\ndependencies = ["typer"]', ['typer']),
    ('[project]\ndependencies = ["rich"]', ['rich']),
    ('[project]\ndependencies = ["pydantic"]', ['pydantic']),
    ('[project]\ndependencies = ["sqlalchemy"]', ['sqlalchemy']),
    ('[project]\ndependencies = ["celery"]', ['celery']),
]


@pytest.mark.parametrize("toml_text, expected", MORE_DEP,
    ids=[f"more-dep-{i}" for i in range(18)])
def test_more_dependencies(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["dependencies"] == expected


MORE_LIC = [
    ('[project]\nname = "pkg"\nlicense = {text = "MIT"}', 'MIT'),
    ('[project]\nname = "pkg"\nlicense = {text = "Apache-2.0"}', 'Apache-2.0'),
    ('[project]\nname = "pkg"\nlicense = {text = "BSD-3-Clause"}', 'BSD-3-Clause'),
    ('[project]\nname = "pkg"\nlicense = {text = "GPL-3.0"}', 'GPL-3.0'),
    ('[project]\nname = "pkg"\nlicense = {text = "LGPL-2.1"}', 'LGPL-2.1'),
    ('[project]\nname = "pkg"\nlicense = {text = "MPL-2.0"}', 'MPL-2.0'),
    ('[project]\nname = "pkg"\nlicense = {text = "ISC"}', 'ISC'),
    ('[project]\nname = "pkg"\nlicense = {text = "Unlicense"}', 'Unlicense'),
    ('[project]\nname = "pkg"\nlicense = {text = "CC0-1.0"}', 'CC0-1.0'),
    ('[project]\nname = "pkg"\nlicense = {text = "BSD-2-Clause"}', 'BSD-2-Clause'),
    ('[project]\nname = "pkg"\nlicense = {text = "AGPL-3.0"}', 'AGPL-3.0'),
    ('[project]\nname = "pkg"\nlicense = {text = "EPL-2.0"}', 'EPL-2.0'),
]


@pytest.mark.parametrize("toml_text, expected", MORE_LIC,
    ids=[f"more-lic-{i}" for i in range(12)])
def test_more_license(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["license"]["text"] == expected


MORE_PYTEST = [
    '[tool.pytest.ini_options]\nxfail_strict = true',
    '[tool.pytest.ini_options]\nasyncio_mode = "auto"',
    '[tool.pytest.ini_options]\nnorecursedirs = ["build", "dist"]',
    '[tool.pytest.ini_options]\ntimeout = 300',
    '[tool.pytest.ini_options]\nfaulthandler_timeout = 5',
    '[tool.pytest.ini_options]\njunit_family = "xunit2"',
    '[tool.pytest.ini_options]\nlog_level = "INFO"',
    '[tool.pytest.ini_options]\nlog_cli_level = "WARNING"',
]


@pytest.mark.parametrize("toml_text", MORE_PYTEST,
    ids=[f"more-pytest-{i}" for i in range(8)])
def test_more_pytest_ini(tmp_path: Path, toml_text: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["tool"]["pytest"]["ini_options"] == {}


EXTRA_COMBO2 = [
    ('[project]\nversion = "1.0.0"\ndependencies = ["numpy"]', {'project': {'version': '1.0.0', 'dependencies': ['numpy']}}),
    ('[project]\nversion = "2.0.0"\ndependencies = ["scipy"]', {'project': {'version': '2.0.0', 'dependencies': ['scipy']}}),
    ('[project]\nversion = "0.1.0"\ndependencies = ["pandas"]', {'project': {'version': '0.1.0', 'dependencies': ['pandas']}}),
    ('[project]\nversion = "3.0.0"\ndependencies = ["click"]', {'project': {'version': '3.0.0', 'dependencies': ['click']}}),
    ('[project]\nversion = "4.0.0"\ndependencies = ["flask"]', {'project': {'version': '4.0.0', 'dependencies': ['flask']}}),
    ('[project]\nversion = "5.0.0"\ndependencies = ["django"]', {'project': {'version': '5.0.0', 'dependencies': ['django']}}),
    ('[project]\nversion = "1.2.3"\ndependencies = ["requests"]', {'project': {'version': '1.2.3', 'dependencies': ['requests']}}),
    ('[project]\nversion = "0.0.1"\ndependencies = ["rich"]', {'project': {'version': '0.0.1', 'dependencies': ['rich']}}),
    ('[project]\nrequires-python = ">=3.8"\n\n[tool.pytest.ini_options]', {'project': {'requires-python': '>=3.8'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.9"\n\n[tool.pytest.ini_options]', {'project': {'requires-python': '>=3.9'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.10"\n\n[tool.pytest.ini_options]', {'project': {'requires-python': '>=3.10'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.11"\n\n[tool.pytest.ini_options]', {'project': {'requires-python': '>=3.11'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nrequires-python = ">=3.12"\n\n[tool.pytest.ini_options]', {'project': {'requires-python': '>=3.12'}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[project]\nversion = "1.0.0"\nlicense = {text = "MIT"}', {'project': {'version': '1.0.0', 'license': {'text': 'MIT'}}}),
    ('[project]\nversion = "2.0.0"\nlicense = {text = "Apache-2.0"}', {'project': {'version': '2.0.0', 'license': {'text': 'Apache-2.0'}}}),
    ('[project]\nversion = "0.1.0"\nlicense = {text = "BSD-3-Clause"}', {'project': {'version': '0.1.0', 'license': {'text': 'BSD-3-Clause'}}}),
    ('[project]\nversion = "3.0.0"\nlicense = {text = "GPL-3.0"}', {'project': {'version': '3.0.0', 'license': {'text': 'GPL-3.0'}}}),
    ('[project]\nversion = "4.0.0"\nlicense = {text = "LGPL-2.1"}', {'project': {'version': '4.0.0', 'license': {'text': 'LGPL-2.1'}}}),
    ('[project]\nlicense = {text = "MIT"}\ndependencies = ["numpy"]', {'project': {'dependencies': ['numpy'], 'license': {'text': 'MIT'}}}),
    ('[project]\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["scipy"]', {'project': {'dependencies': ['scipy'], 'license': {'text': 'BSD-3-Clause'}}}),
    ('[project]\nlicense = {text = "Apache-2.0"}\ndependencies = ["requests"]', {'project': {'dependencies': ['requests'], 'license': {'text': 'Apache-2.0'}}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nversion = "1.0.0"', {'build-system': {'requires': ['hatchling']}, 'project': {'version': '1.0.0'}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nversion = "2.0.0"', {'build-system': {'requires': ['hatchling']}, 'project': {'version': '2.0.0'}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nversion = "0.1.0"', {'build-system': {'requires': ['hatchling']}, 'project': {'version': '0.1.0'}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nversion = "3.0.0"', {'build-system': {'requires': ['hatchling']}, 'project': {'version': '3.0.0'}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\ndependencies = ["numpy"]', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'dependencies': ['numpy']}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\ndependencies = ["scipy"]', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'dependencies': ['scipy']}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\ndependencies = ["pandas"]', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'dependencies': ['pandas']}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\ndependencies = ["requests"]', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'dependencies': ['requests']}}),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_COMBO2,
    ids=[f"xcombo2-{i}" for i in range(29)])
def test_extra_combo_two_fields(tmp_path: Path, toml_text: str, expected: dict) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result == expected


EXTRA_RP_COMPOUND = [
    ('requires-python = ">=3.8,<3.11"', '>=3.8,<3.11'),
    ('requires-python = ">=3.8,<3.10"', '>=3.8,<3.10'),
    ('requires-python = ">=3.9,<3.12"', '>=3.9,<3.12'),
    ('requires-python = ">=3.10,<3.14"', '>=3.10,<3.14'),
    ('requires-python = ">=3.8,!=3.8.0"', '>=3.8,!=3.8.0'),
    ('requires-python = ">=3.9,!=3.9.0,!=3.9.1"', '>=3.9,!=3.9.0,!=3.9.1'),
    ('requires-python = ">=3.8,<3.12,!=3.10.0"', '>=3.8,<3.12,!=3.10.0'),
    ('requires-python = ">=3.7,<3.10,!=3.8.0"', '>=3.7,<3.10,!=3.8.0'),
    ('requires-python = ">=3.11,<4.0"', '>=3.11,<4.0'),
    ('requires-python = ">=3.12,<4.0"', '>=3.12,<4.0'),
    ('requires-python = ">=3.8,<=3.12"', '>=3.8,<=3.12'),
    ('requires-python = ">=3.9,<=3.13"', '>=3.9,<=3.13'),
    ('requires-python = ">3.7,<3.12"', '>3.7,<3.12'),
    ('requires-python = ">3.8,<3.13"', '>3.8,<3.13'),
    ('requires-python = "==3.8.*"', '==3.8.*'),
    ('requires-python = "==3.9.*"', '==3.9.*'),
    ('requires-python = "==3.10.*"', '==3.10.*'),
    ('requires-python = ">=3.8.0"', '>=3.8.0'),
    ('requires-python = ">=3.9.0"', '>=3.9.0'),
    ('requires-python = ">=3.10.0"', '>=3.10.0'),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_RP_COMPOUND,
    ids=[f"xrp-compound-{i}" for i in range(20)])
def test_extra_rp_compound(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["requires-python"] == expected


EXTRA_BS_MULTILINE = [
    ('[build-system]\nrequires = [\n    "setuptools",\n    "wheel",\n    "cython",\n]', ['setuptools', 'wheel', 'cython']),
    ('[build-system]\nrequires = [\n    "setuptools>=42",\n    "wheel",\n    "setuptools-scm",\n]', ['setuptools>=42', 'wheel', 'setuptools-scm']),
    ('[build-system]\nrequires = [\n    "hatchling",\n    "hatch-vcs",\n    "hatch-fancy-pypi-readme",\n]', ['hatchling', 'hatch-vcs', 'hatch-fancy-pypi-readme']),
    ('[build-system]\nrequires = [\n    "flit_core>=3.2",\n    "flit_scm",\n]', ['flit_core>=3.2', 'flit_scm']),
    ('[build-system]\nrequires = [\n    "meson-python>=0.12.1",\n    "cython>=0.29.30",\n    "numpy>=1.20",\n]', ['meson-python>=0.12.1', 'cython>=0.29.30', 'numpy>=1.20']),
    ('[build-system]\nrequires = [\n    "setuptools>=61.0",\n    "setuptools-scm>=6.2",\n]', ['setuptools>=61.0', 'setuptools-scm>=6.2']),
    ('[build-system]\nrequires = [\n    "poetry-core>=1.0.0",\n]', ['poetry-core>=1.0.0']),
    ('[build-system]\nrequires = [\n    "pdm-backend",\n]', ['pdm-backend']),
    ('[build-system]\nrequires = [\n    "scikit-build-core>=0.3.3",\n    "cython>=3.0",\n]', ['scikit-build-core>=0.3.3', 'cython>=3.0']),
    ('[build-system]\nrequires = [\n    "setuptools",\n    "wheel",\n    "numpy",\n    "cython",\n]', ['setuptools', 'wheel', 'numpy', 'cython']),
    ('[build-system]\nrequires = [\n    "hatchling>=1.8.0",\n]', ['hatchling>=1.8.0']),
    ('[build-system]\nrequires = [\n    "flit_core>=3.9",\n]', ['flit_core>=3.9']),
    ('[build-system]\nrequires = [\n    "maturin>=1.0",\n]', ['maturin>=1.0']),
    ('[build-system]\nrequires = [\n    "setuptools>=64",\n    "setuptools-scm>=8",\n]', ['setuptools>=64', 'setuptools-scm>=8']),
    ('[build-system]\nrequires = [\n    "whey",\n]', ['whey']),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_BS_MULTILINE,
    ids=[f"xbs-ml-{i}" for i in range(15)])
def test_extra_bs_multiline(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["build-system"]["requires"] == expected


EXTRA_DEP_MULTILINE = [
    ('[project]\ndependencies = [\n    "numpy",\n    "scipy",\n]', ['numpy', 'scipy']),
    ('[project]\ndependencies = [\n    "requests",\n    "click",\n    "rich",\n]', ['requests', 'click', 'rich']),
    ('[project]\ndependencies = [\n    "pandas",\n    "numpy>=1.20",\n    "pyarrow",\n]', ['pandas', 'numpy>=1.20', 'pyarrow']),
    ('[project]\ndependencies = [\n    "flask",\n    "jinja2",\n    "werkzeug",\n]', ['flask', 'jinja2', 'werkzeug']),
    ('[project]\ndependencies = [\n    "django",\n    "djangorestframework",\n    "django-cors-headers",\n]', ['django', 'djangorestframework', 'django-cors-headers']),
    ('[project]\ndependencies = [\n    "fastapi",\n    "uvicorn",\n    "pydantic",\n]', ['fastapi', 'uvicorn', 'pydantic']),
    ('[project]\ndependencies = [\n    "sqlalchemy",\n    "alembic",\n    "psycopg2",\n]', ['sqlalchemy', 'alembic', 'psycopg2']),
    ('[project]\ndependencies = [\n    "celery",\n    "redis",\n    "kombu",\n]', ['celery', 'redis', 'kombu']),
    ('[project]\ndependencies = [\n    "matplotlib",\n    "seaborn",\n    "plotly",\n]', ['matplotlib', 'seaborn', 'plotly']),
    ('[project]\ndependencies = [\n    "pytest",\n    "coverage",\n    "tox",\n]', ['pytest', 'coverage', 'tox']),
    ('[project]\ndependencies = [\n    "black",\n    "ruff",\n    "mypy",\n]', ['black', 'ruff', 'mypy']),
    ('[project]\ndependencies = [\n    "sphinx",\n    "sphinx-rtd-theme",\n]', ['sphinx', 'sphinx-rtd-theme']),
    ('[project]\ndependencies = [\n    "boto3",\n    "botocore",\n]', ['boto3', 'botocore']),
    ('[project]\ndependencies = [\n    "grpcio",\n    "protobuf",\n]', ['grpcio', 'protobuf']),
    ('[project]\ndependencies = [\n    "pillow",\n    "opencv-python",\n]', ['pillow', 'opencv-python']),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_DEP_MULTILINE,
    ids=[f"xdep-ml-{i}" for i in range(15)])
def test_extra_dep_multiline(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["dependencies"] == expected


REALISTIC_CASES = [
    ('[build-system]\nrequires = ["meson-python>=0.12.1"]\n\n[project]\nname = "numpy"\nversion = "1.26.0"\nrequires-python = ">=3.9"\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["cython>=0.29.30"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['meson-python>=0.12.1']}, 'project': {'requires-python': '>=3.9', 'version': '1.26.0', 'dependencies': ['cython>=0.29.30'], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["meson-python>=0.12.1"]\n\n[project]\nname = "scipy"\nversion = "1.12.0"\nrequires-python = ">=3.9"\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["numpy>=1.22"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['meson-python>=0.12.1']}, 'project': {'requires-python': '>=3.9', 'version': '1.12.0', 'dependencies': ['numpy>=1.22'], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["meson-python>=0.12.1"]\n\n[project]\nname = "pandas"\nversion = "2.1.0"\nrequires-python = ">=3.9"\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["numpy>=1.22", "python-dateutil>=2.8.2"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['meson-python>=0.12.1']}, 'project': {'requires-python': '>=3.9', 'version': '2.1.0', 'dependencies': ['numpy>=1.22', 'python-dateutil>=2.8.2'], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\nname = "flask"\nversion = "3.0.0"\nrequires-python = ">=3.8"\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["werkzeug>=3.0", "jinja2>=3.1"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'requires-python': '>=3.8', 'version': '3.0.0', 'dependencies': ['werkzeug>=3.0', 'jinja2>=3.1'], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools>=42"]\n\n[project]\nname = "django"\nversion = "5.0"\nrequires-python = ">=3.8"\nlicense = {text = "BSD-3-Clause"}\ndependencies = ["asgiref>=3.7"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools>=42']}, 'project': {'requires-python': '>=3.8', 'version': '5.0', 'dependencies': ['asgiref>=3.7'], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nname = "fastapi"\nversion = "0.104.0"\nrequires-python = ">=3.8"\nlicense = {text = "MIT"}\ndependencies = ["starlette>=0.27", "pydantic>=1.7"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['hatchling']}, 'project': {'requires-python': '>=3.8', 'version': '0.104.0', 'dependencies': ['starlette>=0.27', 'pydantic>=1.7'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["flit_core>=3.2"]\n\n[project]\nname = "click"\nversion = "8.1.7"\nrequires-python = ">=3.7"\nlicense = {text = "BSD-3-Clause"}\ndependencies = []\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['flit_core>=3.2']}, 'project': {'requires-python': '>=3.7', 'version': '8.1.7', 'dependencies': [], 'license': {'text': 'BSD-3-Clause'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["poetry-core>=1.0.0"]\n\n[project]\nname = "rich"\nversion = "13.7.0"\nrequires-python = ">=3.7"\nlicense = {text = "MIT"}\ndependencies = ["markdown-it-py>=2.2", "pygments>=2.13"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['poetry-core>=1.0.0']}, 'project': {'requires-python': '>=3.7', 'version': '13.7.0', 'dependencies': ['markdown-it-py>=2.2', 'pygments>=2.13'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nname = "pydantic"\nversion = "2.5.0"\nrequires-python = ">=3.8"\nlicense = {text = "MIT"}\ndependencies = ["typing-extensions>=4.6"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['hatchling']}, 'project': {'requires-python': '>=3.8', 'version': '2.5.0', 'dependencies': ['typing-extensions>=4.6'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["setuptools>=47"]\n\n[project]\nname = "sqlalchemy"\nversion = "2.0.23"\nrequires-python = ">=3.7"\nlicense = {text = "MIT"}\ndependencies = ["typing-extensions>=4.6", "greenlet!=0.4.17"]\n\n[tool.pytest.ini_options]\naddopts = "-v"', {'build-system': {'requires': ['setuptools>=47']}, 'project': {'requires-python': '>=3.7', 'version': '2.0.23', 'dependencies': ['typing-extensions>=4.6', 'greenlet!=0.4.17'], 'license': {'text': 'MIT'}}, 'tool': {'pytest': {'ini_options': {}}}}),
    ('[build-system]\nrequires = ["hatchling"]\n\n[project]\nname = "httpx"\nversion = "0.25.0"\nrequires-python = ">=3.8"\ndependencies = ["httpcore>=0.18", "certifi"]', {'build-system': {'requires': ['hatchling']}, 'project': {'requires-python': '>=3.8', 'version': '0.25.0', 'dependencies': ['httpcore>=0.18', 'certifi']}}),
    ('[build-system]\nrequires = ["setuptools>=42"]\n\n[project]\nname = "aiohttp"\nversion = "3.9.0"\nrequires-python = ">=3.8"\ndependencies = ["aiosignal>=1.1", "attrs>=17.3"]', {'build-system': {'requires': ['setuptools>=42']}, 'project': {'requires-python': '>=3.8', 'version': '3.9.0', 'dependencies': ['aiosignal>=1.1', 'attrs>=17.3']}}),
    ('[build-system]\nrequires = ["setuptools>=42"]\n\n[project]\nname = "celery"\nversion = "5.3.4"\nrequires-python = ">=3.8"\ndependencies = ["billiard>=4.1", "kombu>=5.3"]', {'build-system': {'requires': ['setuptools>=42']}, 'project': {'requires-python': '>=3.8', 'version': '5.3.4', 'dependencies': ['billiard>=4.1', 'kombu>=5.3']}}),
    ('[build-system]\nrequires = ["setuptools>=42"]\n\n[project]\nname = "pytest"\nversion = "7.4.3"\nrequires-python = ">=3.8"\ndependencies = ["iniconfig", "packaging", "pluggy>=0.12"]', {'build-system': {'requires': ['setuptools>=42']}, 'project': {'requires-python': '>=3.8', 'version': '7.4.3', 'dependencies': ['iniconfig', 'packaging', 'pluggy>=0.12']}}),
    ('[build-system]\nrequires = ["hatchling>=1.8.0"]\n\n[project]\nname = "black"\nversion = "23.11.0"\nrequires-python = ">=3.8"\ndependencies = ["click>=8.0", "mypy-extensions>=0.4.3"]', {'build-system': {'requires': ['hatchling>=1.8.0']}, 'project': {'requires-python': '>=3.8', 'version': '23.11.0', 'dependencies': ['click>=8.0', 'mypy-extensions>=0.4.3']}}),
    ('[build-system]\nrequires = ["maturin>=1.0"]\n\n[project]\nname = "ruff"\nversion = "0.1.6"\nrequires-python = ">=3.7"\ndependencies = []', {'build-system': {'requires': ['maturin>=1.0']}, 'project': {'requires-python': '>=3.7', 'version': '0.1.6', 'dependencies': []}}),
    ('[build-system]\nrequires = ["setuptools>=40.6"]\n\n[project]\nname = "mypy"\nversion = "1.7.0"\nrequires-python = ">=3.8"\ndependencies = ["typing-extensions>=4.1"]', {'build-system': {'requires': ['setuptools>=40.6']}, 'project': {'requires-python': '>=3.8', 'version': '1.7.0', 'dependencies': ['typing-extensions>=4.1']}}),
    ('[build-system]\nrequires = ["flit_core>=3.7"]\n\n[project]\nname = "sphinx"\nversion = "7.2.6"\nrequires-python = ">=3.9"\ndependencies = ["sphinxcontrib-applehelp", "Jinja2>=3.0"]', {'build-system': {'requires': ['flit_core>=3.7']}, 'project': {'requires-python': '>=3.9', 'version': '7.2.6', 'dependencies': ['sphinxcontrib-applehelp', 'Jinja2>=3.0']}}),
    ('[build-system]\nrequires = ["hatchling>=1.18"]\n\n[project]\nname = "tox"\nversion = "4.11.3"\nrequires-python = ">=3.8"\ndependencies = ["cachetools>=5.3.1", "packaging>=23.1"]', {'build-system': {'requires': ['hatchling>=1.18']}, 'project': {'requires-python': '>=3.8', 'version': '4.11.3', 'dependencies': ['cachetools>=5.3.1', 'packaging>=23.1']}}),
    ('[build-system]\nrequires = ["setuptools>=42"]\n\n[project]\nname = "pre-commit"\nversion = "3.6.0"\nrequires-python = ">=3.9"\ndependencies = ["cfgv>=2.0", "identify>=1.0"]', {'build-system': {'requires': ['setuptools>=42']}, 'project': {'requires-python': '>=3.9', 'version': '3.6.0', 'dependencies': ['cfgv>=2.0', 'identify>=1.0']}}),
]


@pytest.mark.parametrize("toml_text, expected", REALISTIC_CASES,
    ids=[f"realistic-{i}" for i in range(20)])
def test_realistic_pyproject(tmp_path: Path, toml_text: str, expected: dict) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result == expected


class TestAdditionalEdges:

    def test_rp_single_quotes(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, "requires-python = '>=3.8'"))
        assert result is None or "requires-python" not in result.get("project", {})

    def test_version_in_tool_section(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[tool.black]\nline-length = 88\n\n[project]\nversion = "1.0.0"\n'))
        assert result is not None
        assert result["project"]["version"] == "1.0.0"

    def test_empty_deps_multiline(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[project]\ndependencies = [\n]'))
        assert result is not None
        assert result["project"]["dependencies"] == []

    def test_bs_inline_comment(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, '[build-system]\nrequires = ["setuptools"] # comment\n'))
        assert result is not None
        assert result["build-system"]["requires"] == ["setuptools"]

    def test_file_with_bom(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.toml"
        p.write_bytes(b'\xef\xbb\xbf[project]\nrequires-python = ">=3.8"\n')
        result = _parse_toml_regex(p)
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"

    def test_rp_after_other_keys(self, tmp_path: Path) -> None:
        content = '[project]\nname = "foo"\nversion = "1.0"\ndescription = "A package"\nrequires-python = ">=3.8"\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"
        assert result["project"]["version"] == "1.0"

    def test_only_build_system_requires(self, tmp_path: Path) -> None:
        content = '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["build-system"]["requires"] == ["setuptools"]

    def test_deps_with_pins(self, tmp_path: Path) -> None:
        content = '[project]\ndependencies = ["numpy==1.24.0", "scipy>=1.10,<1.12"]\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["dependencies"] == ["numpy==1.24.0", "scipy>=1.10,<1.12"]

    def test_license_special_chars(self, tmp_path: Path) -> None:
        content = '[project]\nlicense = {text = "BSD 3-Clause License"}\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["project"]["license"]["text"] == "BSD 3-Clause License"

    def test_many_deps(self, tmp_path: Path) -> None:
        deps = [f'dep{i}' for i in range(20)]
        items = ', '.join(f'"{{d}}"' for d in deps)
        content = f'[project]\ndependencies = [{items}]'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert len(result["project"]["dependencies"]) == 20

    def test_no_trailing_newline(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(_write(tmp_path, 'requires-python = ">=3.8"'))
        assert result is not None
        assert result["project"]["requires-python"] == ">=3.8"

    def test_requires_in_different_sections(self, tmp_path: Path) -> None:
        content = '[build-system]\nrequires = ["setuptools"]\n\n[project]\ndependencies = ["numpy"]\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["build-system"]["requires"] == ["setuptools"]
        assert result["project"]["dependencies"] == ["numpy"]

    def test_pytest_between_sections(self, tmp_path: Path) -> None:
        content = '[tool.black]\nline-length = 88\n\n[tool.pytest.ini_options]\naddopts = "-v"\n\n[tool.mypy]\nstrict = true\n'
        result = _parse_toml_regex(_write(tmp_path, content))
        assert result is not None
        assert result["tool"]["pytest"]["ini_options"] == {}

EXTRA_SINGLE_RP = [
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.8"', '>=3.8'),
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.9"', '>=3.9'),
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.10"', '>=3.10'),
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.11"', '>=3.11'),
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.12"', '>=3.12'),
    ('[project]\ndescription = "A package"\nrequires-python = ">=3.13"', '>=3.13'),
    ('[project]\ndescription = "A package"\nrequires-python = ">3.7"', '>3.7'),
    ('[project]\ndescription = "A package"\nrequires-python = ">3.8"', '>3.8'),
    ('[project]\ndescription = "A package"\nrequires-python = ">3.9"', '>3.9'),
    ('[project]\ndescription = "A package"\nrequires-python = "==3.8"', '==3.8'),
    ('[project]\ndescription = "A package"\nrequires-python = "==3.9"', '==3.9'),
    ('[project]\ndescription = "A package"\nrequires-python = "==3.10"', '==3.10'),
    ('[project]\ndescription = "A package"\nrequires-python = "==3.11"', '==3.11'),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_SINGLE_RP,
    ids=[f"xsrp-{i}" for i in range(13)])
def test_extra_single_rp(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["requires-python"] == expected


EXTRA_SINGLE_VER = [
    ('[project]\ndescription = "A package"\nversion = "0.1.0"', '0.1.0'),
    ('[project]\ndescription = "A package"\nversion = "0.2.0"', '0.2.0'),
    ('[project]\ndescription = "A package"\nversion = "0.3.0"', '0.3.0'),
    ('[project]\ndescription = "A package"\nversion = "1.0.0"', '1.0.0'),
    ('[project]\ndescription = "A package"\nversion = "1.1.0"', '1.1.0'),
    ('[project]\ndescription = "A package"\nversion = "1.2.0"', '1.2.0'),
    ('[project]\ndescription = "A package"\nversion = "2.0.0"', '2.0.0'),
    ('[project]\ndescription = "A package"\nversion = "2.1.0"', '2.1.0'),
    ('[project]\ndescription = "A package"\nversion = "3.0.0"', '3.0.0'),
    ('[project]\ndescription = "A package"\nversion = "4.0.0"', '4.0.0'),
    ('[project]\ndescription = "A package"\nversion = "5.0.0"', '5.0.0'),
    ('[project]\ndescription = "A package"\nversion = "10.0.0"', '10.0.0'),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_SINGLE_VER,
    ids=[f"xsver-{i}" for i in range(12)])
def test_extra_single_ver(tmp_path: Path, toml_text: str, expected: str) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["version"] == expected


EXTRA_SINGLE_DEPS = [
    ('[project]\ndependencies = ["torch"]', ['torch']),
    ('[project]\ndependencies = ["tensorflow"]', ['tensorflow']),
    ('[project]\ndependencies = ["jax"]', ['jax']),
    ('[project]\ndependencies = ["transformers"]', ['transformers']),
    ('[project]\ndependencies = ["datasets"]', ['datasets']),
    ('[project]\ndependencies = ["tokenizers"]', ['tokenizers']),
    ('[project]\ndependencies = ["accelerate"]', ['accelerate']),
    ('[project]\ndependencies = ["diffusers"]', ['diffusers']),
    ('[project]\ndependencies = ["gradio"]', ['gradio']),
    ('[project]\ndependencies = ["streamlit"]', ['streamlit']),
]


@pytest.mark.parametrize("toml_text, expected", EXTRA_SINGLE_DEPS,
    ids=[f"xsdep-{i}" for i in range(10)])
def test_extra_single_deps(tmp_path: Path, toml_text: str, expected: list) -> None:
    result = _parse_toml_regex(_write(tmp_path, toml_text))
    assert result is not None
    assert result["project"]["dependencies"] == expected


