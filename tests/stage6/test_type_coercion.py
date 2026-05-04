"""Dimension 3 — Type Coercion / Mismatch tests for detect_repo_specs.py.

Every public function is called with wrong-typed arguments to verify it
raises a sensible exception (TypeError, AttributeError, etc.) rather than
silently returning garbage.  200+ parametrized cases in total.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import setup: add scripts/ to path so we can import detect_repo_specs
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _detect_log_parser_type,
    _parse_min_python,
    _parse_toml,
    _parse_toml_regex,
    _read_text,
    check_license,
    detect_all_specs,
    detect_install_cmd,
    detect_packages_source,
    detect_pre_install,
    detect_python_version,
    detect_test_cmd,
    detect_version,
    load_cache,
    save_cache,
    validate_instances,
    write_jsonl,
)

_SENTINEL_OBJ = object()
_SENTINEL_LAMBDA = lambda: None  # noqa: E731

# Exceptions any of these functions may raise on wrong types
_TYPE_ERRORS = (TypeError, AttributeError, ValueError, OSError)


def _bad_types_for_path() -> list[tuple[str, object]]:
    return [
        ("int", 42),
        ("float", 3.14),
        ("bool-true", True),
        ("bool-false", False),
        ("none", None),
        ("list-empty", []),
        ("list-str", ["/tmp"]),
        ("dict-empty", {}),
        ("dict-str", {"path": "/tmp"}),
        ("bytes", b"/tmp"),
        ("frozenset", frozenset({1, 2})),
        ("set", {1, 2, 3}),
        ("tuple", ("/tmp",)),
        ("complex", 1 + 2j),
        ("object", _SENTINEL_OBJ),
        ("lambda", _SENTINEL_LAMBDA),
    ]


def _bad_types_for_str() -> list[tuple[str, object]]:
    return [
        ("int", 42),
        ("float", 3.14),
        ("bool-true", True),
        ("bool-false", False),
        ("none", None),
        ("list-empty", []),
        ("list-str", ["hello"]),
        ("dict-empty", {}),
        ("dict-str", {"k": "v"}),
        ("bytes", b"hello"),
        ("path", Path("/tmp")),
        ("frozenset", frozenset({"a"})),
        ("set", {"a", "b"}),
        ("tuple", ("a",)),
        ("complex", 3 + 4j),
        ("object", _SENTINEL_OBJ),
        ("lambda", _SENTINEL_LAMBDA),
    ]


# Non-scalar, non-string types that the `in` operator accepts without error
# (containers support __contains__), so _detect_log_parser_type won't raise.
_STR_TYPES_THAT_RAISE = [
    ("int", 42),
    ("float", 3.14),
    ("bool-true", True),
    ("bool-false", False),
    ("none", None),
    ("bytes", b"hello"),
    ("path", Path("/tmp")),
    ("complex", 3 + 4j),
    ("object", _SENTINEL_OBJ),
    ("lambda", _SENTINEL_LAMBDA),
]


# ═══════════════════════════════════════════════════════════════════════
# 1. _read_text — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestReadTextTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            _read_text(value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, value",
        [
            ("str-not-path", "not_a_real_file.txt"),
            ("str-empty", ""),
            ("str-slash", "/"),
        ],
        ids=["str-not-path", "str-empty", "str-slash"],
    )
    def test_str_raises_attribute_error(self, label: str, value: str) -> None:
        # _read_text calls path.read_text() which str doesn't have
        with pytest.raises(AttributeError):
            _read_text(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 2. _parse_toml and _parse_toml_regex — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestParseTomlTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[f"toml-{t[0]}" for t in _bad_types_for_path()],
    )
    def test_parse_toml_wrong_type(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            _parse_toml(value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[f"toml_regex-{t[0]}" for t in _bad_types_for_path()],
    )
    def test_parse_toml_regex_wrong_type(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            _parse_toml_regex(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 3. _parse_min_python — expects str
# ═══════════════════════════════════════════════════════════════════════

class TestParseMinPythonTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_str(),
        ids=[t[0] for t in _bad_types_for_str()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(TypeError):
            _parse_min_python(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 4. detect_python_version — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestDetectPythonVersionTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_python_version(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 5. detect_install_cmd — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestDetectInstallCmdTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_install_cmd(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 6. detect_test_cmd — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestDetectTestCmdTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_test_cmd(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 7. detect_packages_source — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestDetectPackagesSourceTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_packages_source(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 8. detect_pre_install — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestDetectPreInstallTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_pre_install(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 9. detect_version — expects (Path, str)
# ═══════════════════════════════════════════════════════════════════════

class TestDetectVersionTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[f"repo_dir-{t[0]}" for t in _bad_types_for_path()],
    )
    def test_bad_repo_dir(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_version(value, "owner/repo")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_str(),
        ids=[f"repo_name-{t[0]}" for t in _bad_types_for_str()],
    )
    def test_bad_repo_name(self, label: str, value: object, repo: Path) -> None:
        # repo_name.split("/") — non-str types raise AttributeError or TypeError
        with pytest.raises(_TYPE_ERRORS):
            detect_version(repo, value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 10. check_license — expects Path
# ═══════════════════════════════════════════════════════════════════════

class TestCheckLicenseTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[t[0] for t in _bad_types_for_path()],
    )
    def test_wrong_type_raises(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            check_license(value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 11. _detect_log_parser_type — expects str
# ═══════════════════════════════════════════════════════════════════════

class TestDetectLogParserTypeCoercion:

    # Types that definitely raise (non-containers, non-iterables where `in` fails)
    @pytest.mark.parametrize(
        "label, value",
        _STR_TYPES_THAT_RAISE,
        ids=[t[0] for t in _STR_TYPES_THAT_RAISE],
    )
    def test_non_container_raises(self, label: str, value: object) -> None:
        with pytest.raises(TypeError):
            _detect_log_parser_type(value)  # type: ignore[arg-type]

    # Containers silently return "pytest" (default) — `in` works on them
    @pytest.mark.parametrize(
        "label, value",
        [
            ("list-empty", []),
            ("list-str", ["hello"]),
            ("dict-empty", {}),
            ("dict-str", {"k": "v"}),
            ("frozenset-empty", frozenset()),
            ("frozenset-str", frozenset({"a"})),
            ("set-empty", set()),
            ("set-str", {"a", "b"}),
            ("tuple-empty", ()),
            ("tuple-str", ("a",)),
        ],
        ids=[
            "container-list-empty",
            "container-list-str",
            "container-dict-empty",
            "container-dict-str",
            "container-frozenset-empty",
            "container-frozenset-str",
            "container-set-empty",
            "container-set-str",
            "container-tuple-empty",
            "container-tuple-str",
        ],
    )
    def test_container_returns_default(self, label: str, value: object) -> None:
        # `in` works on containers but never matches the expected substrings
        result = _detect_log_parser_type(value)  # type: ignore[arg-type]
        assert result == "pytest"


# ═══════════════════════════════════════════════════════════════════════
# 12. detect_all_specs — expects (Path, str)
# ═══════════════════════════════════════════════════════════════════════

class TestDetectAllSpecsTypeCoercion:

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_path(),
        ids=[f"repo_dir-{t[0]}" for t in _bad_types_for_path()],
    )
    def test_bad_repo_dir(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_all_specs(value, "owner/repo")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, value",
        _bad_types_for_str(),
        ids=[f"repo-{t[0]}" for t in _bad_types_for_str()],
    )
    def test_bad_repo(self, label: str, value: object, repo: Path) -> None:
        with pytest.raises(_TYPE_ERRORS):
            detect_all_specs(repo, value)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# 13. IO functions — load_cache, save_cache, write_jsonl, validate_instances
# ═══════════════════════════════════════════════════════════════════════

class TestIOTypeCoercion:

    # -- load_cache(cache_file: str) ----------------------------------------
    # Path objects silently work (os.path.exists accepts Path), all others raise.

    @pytest.mark.parametrize(
        "label, value",
        [
            ("int", 42),
            ("float", 3.14),
            ("bool-true", True),
            ("bool-false", False),
            ("none", None),
            ("list-empty", []),
            ("dict-empty", {}),
            ("bytes", b"cache.json"),
            ("frozenset", frozenset()),
            ("complex", 1j),
            ("object", _SENTINEL_OBJ),
            ("lambda", _SENTINEL_LAMBDA),
            ("tuple", ("a",)),
            ("set", {"a"}),
        ],
        ids=[
            "load_cache-int",
            "load_cache-float",
            "load_cache-bool-true",
            "load_cache-bool-false",
            "load_cache-none",
            "load_cache-list",
            "load_cache-dict",
            "load_cache-bytes",
            "load_cache-frozenset",
            "load_cache-complex",
            "load_cache-object",
            "load_cache-lambda",
            "load_cache-tuple",
            "load_cache-set",
        ],
    )
    def test_load_cache_bad_type(self, label: str, value: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            load_cache(value)  # type: ignore[arg-type]

    def test_load_cache_path_obj_returns_empty(self, tmp_path: Path) -> None:
        # Path objects duck-type into os.path.exists, non-existent → empty dict
        result = load_cache(tmp_path / "nonexistent.json")  # type: ignore[arg-type]
        assert result == {}

    # -- save_cache(cache: dict, cache_file: str) ---------------------------
    # json.dump raises TypeError on non-serialisable first args.
    # str and list are json-serialisable so they silently succeed.

    @pytest.mark.parametrize(
        "label, bad_cache",
        [
            ("cache-int", 42),
            ("cache-none", None),
            ("cache-bool", True),
            ("cache-bytes", b"data"),
            ("cache-frozenset", frozenset()),
            ("cache-complex", 1j),
            ("cache-object", _SENTINEL_OBJ),
            ("cache-lambda", _SENTINEL_LAMBDA),
            ("cache-set", {1, 2}),
            ("cache-path", Path("/tmp")),
        ],
        ids=[
            "save_cache-cache-int",
            "save_cache-cache-none",
            "save_cache-cache-bool",
            "save_cache-cache-bytes",
            "save_cache-cache-frozenset",
            "save_cache-cache-complex",
            "save_cache-cache-object",
            "save_cache-cache-lambda",
            "save_cache-cache-set",
            "save_cache-cache-path",
        ],
    )
    def test_save_cache_bad_cache_type(
        self, label: str, bad_cache: object, tmp_path: Path
    ) -> None:
        with pytest.raises(_TYPE_ERRORS):
            save_cache(bad_cache, str(tmp_path / "c.json"))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, bad_file",
        [
            ("file-int", 42),
            ("file-float", 3.14),
            ("file-none", None),
            ("file-list", []),
            ("file-dict", {}),
            ("file-bool", True),
            ("file-bytes", b"/tmp/c.json"),
            ("file-frozenset", frozenset()),
            ("file-complex", 1j),
            ("file-object", _SENTINEL_OBJ),
            ("file-lambda", _SENTINEL_LAMBDA),
            ("file-set", {"a"}),
            ("file-tuple", ("a",)),
        ],
        ids=[
            "save_cache-file-int",
            "save_cache-file-float",
            "save_cache-file-none",
            "save_cache-file-list",
            "save_cache-file-dict",
            "save_cache-file-bool",
            "save_cache-file-bytes",
            "save_cache-file-frozenset",
            "save_cache-file-complex",
            "save_cache-file-object",
            "save_cache-file-lambda",
            "save_cache-file-set",
            "save_cache-file-tuple",
        ],
    )
    def test_save_cache_bad_file_type(self, label: str, bad_file: object) -> None:
        with pytest.raises(_TYPE_ERRORS):
            save_cache({}, bad_file)  # type: ignore[arg-type]

    def test_save_cache_path_obj_succeeds(self, tmp_path: Path) -> None:
        # Path objects duck-type into open() — silently works
        save_cache({"k": 1}, tmp_path / "c.json")  # type: ignore[arg-type]

    # -- write_jsonl(instances: list, output_path: str) ---------------------
    # Iterables silently succeed since the function iterates and json.dumps each item.

    @pytest.mark.parametrize(
        "label, bad_instances",
        [
            ("inst-int", 42),
            ("inst-none", None),
            ("inst-bool", True),
            ("inst-float", 3.14),
            ("inst-complex", 1j),
            ("inst-object", _SENTINEL_OBJ),
            ("inst-lambda", _SENTINEL_LAMBDA),
        ],
        ids=[
            "write_jsonl-inst-int",
            "write_jsonl-inst-none",
            "write_jsonl-inst-bool",
            "write_jsonl-inst-float",
            "write_jsonl-inst-complex",
            "write_jsonl-inst-object",
            "write_jsonl-inst-lambda",
        ],
    )
    def test_write_jsonl_bad_instances_raises(
        self, label: str, bad_instances: object, tmp_path: Path
    ) -> None:
        with pytest.raises(_TYPE_ERRORS):
            write_jsonl(bad_instances, str(tmp_path / "out.jsonl"))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, bad_instances",
        [
            ("inst-str", "hello"),
            ("inst-dict", {"a": 1}),
            ("inst-bytes", b"data"),
            ("inst-frozenset", frozenset()),
            ("inst-set", {1, 2}),
            ("inst-tuple", ((1,), (2,))),
        ],
        ids=[
            "write_jsonl-inst-str-iterates",
            "write_jsonl-inst-dict-iterates",
            "write_jsonl-inst-bytes-iterates",
            "write_jsonl-inst-frozenset-iterates",
            "write_jsonl-inst-set-iterates",
            "write_jsonl-inst-tuple-iterates",
        ],
    )
    def test_write_jsonl_iterable_silently_succeeds(
        self, label: str, bad_instances: object, tmp_path: Path
    ) -> None:
        # These are iterable, so the function loops over them without error
        p = tmp_path / "out.jsonl"
        write_jsonl(bad_instances, str(p))  # type: ignore[arg-type]
        assert p.exists()

    @pytest.mark.parametrize(
        "label, bad_path",
        [
            ("path-int", 42),
            ("path-float", 3.14),
            ("path-none", None),
            ("path-list", []),
            ("path-dict", {}),
            ("path-bool", True),
            ("path-bytes", b"/tmp/out.jsonl"),
            ("path-frozenset", frozenset()),
            ("path-complex", 2j),
            ("path-object", _SENTINEL_OBJ),
            ("path-lambda", _SENTINEL_LAMBDA),
            ("path-set", {"a"}),
            ("path-tuple", ("a",)),
        ],
        ids=[
            "write_jsonl-path-int",
            "write_jsonl-path-float",
            "write_jsonl-path-none",
            "write_jsonl-path-list",
            "write_jsonl-path-dict",
            "write_jsonl-path-bool",
            "write_jsonl-path-bytes",
            "write_jsonl-path-frozenset",
            "write_jsonl-path-complex",
            "write_jsonl-path-object",
            "write_jsonl-path-lambda",
            "write_jsonl-path-set",
            "write_jsonl-path-tuple",
        ],
    )
    def test_write_jsonl_bad_path_raises(
        self, label: str, bad_path: object
    ) -> None:
        with pytest.raises(_TYPE_ERRORS):
            write_jsonl([], bad_path)  # type: ignore[arg-type]

    def test_write_jsonl_path_obj_succeeds(self, tmp_path: Path) -> None:
        # Path objects duck-type into open()
        p = tmp_path / "out.jsonl"
        write_jsonl([{"a": 1}], p)  # type: ignore[arg-type]
        assert p.exists()

    # -- validate_instances(instances: list) --------------------------------
    # Iterates over instances; empty iterables silently return True.

    @pytest.mark.parametrize(
        "label, bad_instances",
        [
            ("inst-int", 42),
            ("inst-none", None),
            ("inst-bool", True),
            ("inst-float", 3.14),
            ("inst-complex", 1j),
            ("inst-object", _SENTINEL_OBJ),
            ("inst-lambda", _SENTINEL_LAMBDA),
        ],
        ids=[
            "validate-int",
            "validate-none",
            "validate-bool",
            "validate-float",
            "validate-complex",
            "validate-object",
            "validate-lambda",
        ],
    )
    def test_validate_instances_non_iterable_raises(
        self, label: str, bad_instances: object
    ) -> None:
        with pytest.raises(TypeError):
            validate_instances(bad_instances)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "label, bad_instances",
        [
            ("inst-str", "hello"),
            ("inst-dict", {"a": 1}),
            ("inst-bytes", b"data"),
            ("inst-set", {1, 2}),
            ("inst-path", Path("/tmp")),
        ],
        ids=[
            "validate-str-iterates",
            "validate-dict-iterates",
            "validate-bytes-iterates",
            "validate-set-iterates",
            "validate-path-iterates",
        ],
    )
    def test_validate_instances_iterable_raises_on_element(
        self, label: str, bad_instances: object
    ) -> None:
        # These are iterable but their elements aren't dicts → AttributeError
        with pytest.raises((TypeError, AttributeError)):
            validate_instances(bad_instances)  # type: ignore[arg-type]

    def test_validate_instances_empty_frozenset_returns_true(self) -> None:
        # Empty iterable → loop body never executes → returns True
        assert validate_instances(frozenset()) is True  # type: ignore[arg-type]
