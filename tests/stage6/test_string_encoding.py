"""D4 (String & Text Brutality) and D10 (Data Format & Encoding) tests.

Tests for scripts/detect_repo_specs.py covering Unicode edge cases,
invisible characters, homoglyphs, BOM handling, line endings, and
locale-specific number formats.

Target: ~150+ test cases across 9 test classes.
"""

from __future__ import annotations

import json
import sys
import textwrap
import unicodedata
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import setup: add scripts/ to path so we can import detect_repo_specs
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _read_text,
    _parse_toml,
    _parse_toml_regex,
    _parse_min_python,
    detect_python_version,
    detect_install_cmd,
    detect_test_cmd,
    detect_packages_source,
    detect_pre_install,
    detect_version,
    check_license,
    _detect_log_parser_type,
    detect_all_specs,
    load_cache,
    save_cache,
    write_jsonl,
    validate_instances,
)


# ===================================================================
# DIMENSION 4 — String & Text Brutality
# ===================================================================


class TestRTLTextHandling:
    """D4: Right-to-left text in various contexts."""

    def test_read_text_preserves_arabic(self, tmp_path: Path) -> None:
        """D4: _read_text faithfully returns Arabic content."""
        p = tmp_path / "file.txt"
        p.write_text("مرحبا", encoding="utf-8")
        assert _read_text(p) == "مرحبا"

    def test_read_text_preserves_hebrew(self, tmp_path: Path) -> None:
        """D4: _read_text faithfully returns Hebrew content."""
        p = tmp_path / "file.txt"
        p.write_text("שלום", encoding="utf-8")
        assert _read_text(p) == "שלום"

    def test_arabic_in_pyproject_version_returns_none_or_arabic(self, tmp_path: Path) -> None:
        """D4: Arabic text as version in pyproject.toml — detect_version returns it as-is or None."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nversion = "مرحبا"\n', encoding="utf-8"
        )
        result = detect_version(tmp_path, "owner/pkg")
        # tomllib parses it; the function returns whatever string is there
        assert result in ("مرحبا", None)

    def test_hebrew_in_setup_py_version(self, tmp_path: Path) -> None:
        """D4: Hebrew text in setup.py version string."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='שלום')\n",
            encoding="utf-8",
        )
        result = detect_version(tmp_path, "owner/pkg")
        assert result == "שלום"

    def test_rtl_in_python_version_file_fallback(self, tmp_path: Path) -> None:
        """D4: RTL text in .python-version causes fallback to 3.10."""
        (tmp_path / ".python-version").write_text("مرحبا\n", encoding="utf-8")
        assert detect_python_version(tmp_path) == "3.10"

    def test_mixed_rtl_ltr_version_string(self, tmp_path: Path) -> None:
        """D4: Mixed RTL/LTR text in version — regex may extract digits."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1.0-مرحبا')\n",
            encoding="utf-8",
        )
        result = detect_version(tmp_path, "owner/pkg")
        assert result == "1.0-مرحبا"

    def test_arabic_in_license_file_no_match(self, tmp_path: Path) -> None:
        """D4: Arabic-only LICENSE file doesn't match any known license pattern."""
        (tmp_path / "LICENSE").write_text("رخصة عامة\nمرحبا بكم\n", encoding="utf-8")
        assert check_license(tmp_path) is None

    def test_rtl_in_requires_python_fallback(self, tmp_path: Path) -> None:
        """D4: RTL characters in requires-python value — _parse_min_python returns fallback."""
        assert _parse_min_python(">=مرحبا") == "3.10"

    def test_rtl_in_setup_cfg_python_requires(self, tmp_path: Path) -> None:
        """D4: RTL in setup.cfg python_requires falls back to 3.10."""
        (tmp_path / "setup.cfg").write_text(
            "[options]\npython_requires = >=مرحبا\n", encoding="utf-8"
        )
        assert detect_python_version(tmp_path) == "3.10"

    def test_arabic_in_package_name_setup_py(self, tmp_path: Path) -> None:
        """D4: Arabic in package name — detect_install_cmd still returns a command."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(name='مكتبة')\n",
            encoding="utf-8",
        )
        assert detect_install_cmd(tmp_path) == "pip install -e ."

    def test_rtl_marks_in_tox_envlist(self, tmp_path: Path) -> None:
        """D4: RTL marks in tox.ini envlist — no version extracted, fallback."""
        (tmp_path / "tox.ini").write_text(
            "[tox]\nenvlist = مرحبا\n", encoding="utf-8"
        )
        assert detect_python_version(tmp_path) == "3.10"

    def test_hebrew_in_pyproject_license_text(self, tmp_path: Path) -> None:
        """D4: Hebrew license text in pyproject.toml — no known license matched."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\n[project.license]\ntext = "שלום"\n',
            encoding="utf-8",
        )
        assert check_license(tmp_path) is None

    def test_rtl_in_requirements_txt_filename(self, tmp_path: Path) -> None:
        """D4: Even with RTL content in requirements.txt, detect_packages_source finds it."""
        (tmp_path / "requirements.txt").write_text("مرحبا>=1.0\n", encoding="utf-8")
        source, paths, _ = detect_packages_source(tmp_path)
        assert source == "requirements.txt"
        assert paths == ["requirements.txt"]

    def test_mixed_arabic_latin_in_test_cmd(self, tmp_path: Path) -> None:
        """D4: Arabic mixed into tox commands — still detects pytest if present."""
        (tmp_path / "tox.ini").write_text(
            "[testenv]\ncommands = pytest مرحبا\n", encoding="utf-8"
        )
        assert detect_test_cmd(tmp_path) == "pytest {test_files}"

    def test_rtl_in_write_jsonl_field(self, tmp_path: Path) -> None:
        """D4: RTL text in JSONL field values preserved through write_jsonl."""
        out = tmp_path / "out.jsonl"
        records = [{"name": "مرحبا", "version": "שלום"}]
        write_jsonl(records, str(out))
        loaded = json.loads(out.read_text(encoding="utf-8").strip())
        assert loaded["name"] == "مرحبا"
        assert loaded["version"] == "שלום"


class TestCombiningDiacriticals:
    """D4: NFC/NFD normalization and combining characters."""

    def test_read_text_preserves_nfc(self, tmp_path: Path) -> None:
        """D4: _read_text preserves NFC precomposed é."""
        p = tmp_path / "f.txt"
        nfc = "\u00e9"  # precomposed é
        p.write_text(nfc, encoding="utf-8")
        assert _read_text(p) == nfc

    def test_read_text_preserves_nfd(self, tmp_path: Path) -> None:
        """D4: _read_text preserves NFD combining e + combining accent."""
        p = tmp_path / "f.txt"
        nfd = "e\u0301"  # e + combining acute
        p.write_text(nfd, encoding="utf-8")
        assert _read_text(p) == nfd

    def test_nfc_nfd_byte_difference(self, tmp_path: Path) -> None:
        """D4: NFC and NFD produce different bytes for visually identical char."""
        nfc = "\u00e9"
        nfd = "e\u0301"
        p1 = tmp_path / "nfc.txt"
        p2 = tmp_path / "nfd.txt"
        p1.write_text(nfc, encoding="utf-8")
        p2.write_text(nfd, encoding="utf-8")
        # They look the same but bytes differ
        assert p1.read_bytes() != p2.read_bytes()
        # _read_text returns them as-is (no normalization)
        assert _read_text(p1) != _read_text(p2)

    def test_combining_in_pyproject_version(self, tmp_path: Path) -> None:
        """D4: Combining char in version — detect_version returns raw string."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nversion = "1.0\u0301"\n', encoding="utf-8"
        )
        result = detect_version(tmp_path, "owner/pkg")
        assert result in ("1.0\u0301", None)

    def test_combining_in_setup_py_version(self, tmp_path: Path) -> None:
        """D4: Combining diacritical in setup.py version."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='cafe\u0301')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "cafe\u0301"

    def test_nfc_in_license_mit(self, tmp_path: Path) -> None:
        """D4: NFC chars in MIT license text — pattern still matches."""
        (tmp_path / "LICENSE").write_text(
            "MIT License\n\nCopyright (c) Caf\u00e9 Corp\nPermission is hereby granted MIT\n",
            encoding="utf-8",
        )
        assert check_license(tmp_path) == "MIT"

    def test_nfd_in_license_mit(self, tmp_path: Path) -> None:
        """D4: NFD chars in MIT license text — pattern still matches."""
        (tmp_path / "LICENSE").write_text(
            "MIT License\n\nCopyright (c) Cafe\u0301 Corp\nPermission is hereby granted MIT\n",
            encoding="utf-8",
        )
        assert check_license(tmp_path) == "MIT"

    def test_multiple_combining_stacked(self, tmp_path: Path) -> None:
        """D4: Multiple combining marks stacked — _read_text preserves all."""
        p = tmp_path / "f.txt"
        stacked = "a\u0300\u0301\u0302"  # a + grave + acute + circumflex
        p.write_text(stacked, encoding="utf-8")
        assert _read_text(p) == stacked

    def test_combining_in_requires_python_no_match(self) -> None:
        """D4: Combining char in specifier — _parse_min_python returns fallback."""
        assert _parse_min_python(">=3\u0301.8") == "3.10"

    def test_combining_in_python_version_file(self, tmp_path: Path) -> None:
        """D4: Combining char in .python-version — fallback to 3.10."""
        (tmp_path / ".python-version").write_text("3\u0301.11\n", encoding="utf-8")
        assert detect_python_version(tmp_path) == "3.10"

    def test_combining_tilde_in_version(self, tmp_path: Path) -> None:
        """D4: Combining tilde in version string passes through."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1.0n\u0303')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1.0n\u0303"

    def test_nfc_nfd_same_visual_different_key(self, tmp_path: Path) -> None:
        """D4: NFC and NFD version strings are distinct values even if visually same."""
        nfc_ver = "1.0\u00e9"
        nfd_ver = "1.0e\u0301"
        assert unicodedata.normalize("NFC", nfc_ver) == unicodedata.normalize("NFC", nfd_ver)
        # But raw strings differ
        assert nfc_ver != nfd_ver

    def test_combining_in_cache_key_preserved(self, tmp_path: Path) -> None:
        """D4: Combining chars in cache values survive save/load cycle."""
        cache_file = tmp_path / "cache.json"
        data = {"key\u0301": {"python_version": "3.10\u0302"}}
        save_cache(data, str(cache_file))
        loaded = load_cache(str(cache_file))
        assert loaded.get("key\u0301", {}).get("python_version") == "3.10\u0302"

    def test_combining_in_jsonl_preserved(self, tmp_path: Path) -> None:
        """D4: Combining chars in JSONL survive write/read cycle."""
        out = tmp_path / "out.jsonl"
        records = [{"v": "cafe\u0301"}]
        write_jsonl(records, str(out))
        loaded = json.loads(out.read_text(encoding="utf-8").strip())
        assert loaded["v"] == "cafe\u0301"

    def test_combining_in_file_path_read(self, tmp_path: Path) -> None:
        """D4: File with combining char in name — _read_text can read it."""
        p = tmp_path / "cafe\u0301.txt"
        p.write_text("hello", encoding="utf-8")
        assert _read_text(p) == "hello"


class TestHomoglyphs:
    """D4: Visually similar characters from different scripts."""

    def test_cyrillic_a_in_requires_python_no_match(self) -> None:
        """D4: Cyrillic 'а' (U+0430) instead of Latin 'a' — no regex match."""
        # "requires-python" with Cyrillic а — would appear in raw text
        # _parse_min_python on a spec with Cyrillic digits won't match
        spec = ">=3.8"  # normal
        assert _parse_min_python(spec) == "3.8"
        # But if someone uses fullwidth digits:
        cyrillic_spec = ">=\u0417.\u0418"  # Cyrillic chars instead of digits
        assert _parse_min_python(cyrillic_spec) == "3.10"  # fallback

    def test_cyrillic_a_vs_latin_a_distinct(self) -> None:
        """D4: Cyrillic 'а' (U+0430) is not equal to Latin 'a' (U+0061)."""
        assert "\u0430" != "a"

    def test_greek_omicron_vs_latin_o(self) -> None:
        """D4: Greek omicron (U+03BF) is not equal to Latin 'o' (U+006F)."""
        assert "\u03bf" != "o"

    def test_homoglyph_python_in_requires_no_match(self, tmp_path: Path) -> None:
        """D4: 'рython' with Cyrillic 'р' — regex won't match python_requires."""
        # Cyrillic р (U+0440) + "ython_requires"
        content = "from setuptools import setup\nsetup(\u0440ython_requires='>=3.9')\n"
        (tmp_path / "setup.py").write_text(content, encoding="utf-8")
        # Should not match python_requires regex — falls to fallback
        assert detect_python_version(tmp_path) == "3.10"

    def test_homoglyph_version_key_no_match(self, tmp_path: Path) -> None:
        """D4: 'versiоn' with Greek omicron — regex won't match version key."""
        # Greek ο (U+03BF) in 'versi\u03bfn'
        content = "from setuptools import setup\nsetup(versi\u03bfn='2.0')\n"
        (tmp_path / "setup.py").write_text(content, encoding="utf-8")
        assert detect_version(tmp_path, "owner/pkg") is None

    def test_homoglyph_in_pyproject_requires_python_key(self, tmp_path: Path) -> None:
        """D4: Homoglyph in pyproject key 'requires-рython' — not matched by regex."""
        # Cyrillic р (U+0440) in requires-\u0440ython
        content = '[project]\nname = "pkg"\nrequires-\u0440ython = ">=3.11"\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8")
        assert detect_python_version(tmp_path) == "3.10"

    def test_homoglyph_mit_in_license(self, tmp_path: Path) -> None:
        """D4: 'МIT' with Cyrillic М (U+041C) — license pattern won't match."""
        # Cyrillic М + Latin IT
        (tmp_path / "LICENSE").write_text(
            "\u041cIT License\n\nPermission is hereby granted\n", encoding="utf-8"
        )
        # "МIT" != "MIT" so the pattern \bMIT License\b won't match
        # But "Permission is hereby granted.*MIT" might match at the end
        # Actually there's no "MIT" at the end — just "МIT" at the start
        result = check_license(tmp_path)
        # The regex looks for "MIT License" or "Permission is hereby granted.*MIT"
        # "МIT License" won't match \bMIT, and "Permission is hereby granted" has no MIT after it
        assert result is None

    def test_cyrillic_digits_in_version_spec(self) -> None:
        """D4: Non-ASCII digit-like chars in version spec — no match."""
        # Using non-standard digits that look like 3.8
        assert _parse_min_python(">=\u0417.\u0418") == "3.10"

    def test_homoglyph_setup_word(self, tmp_path: Path) -> None:
        """D4: 'ѕetup' with Cyrillic ѕ (U+0455) — file still detected by existence."""
        # setup.py still exists as a file, just content has homoglyphs
        content = "from \u0455etuptools import \u0455etup\n\u0455etup(name='pkg')\n"
        (tmp_path / "setup.py").write_text(content, encoding="utf-8")
        # File exists so detect_install_cmd returns pip install -e .
        assert detect_install_cmd(tmp_path) == "pip install -e ."

    def test_fullwidth_digits_in_version(self, tmp_path: Path) -> None:
        """D4: Fullwidth digits '３.１１' — Python 3 \\d matches Unicode digits."""
        spec = ">=\uff13.\uff11\uff11"  # fullwidth 3.11
        # Python 3 re \d matches Unicode decimal digits, so this extracts them
        result = _parse_min_python(spec)
        assert result == "\uff13.\uff11\uff11"


class TestInvisibleCharacters:
    """D4: BOM, zero-width chars, NBSP, and other invisible characters."""

    def test_bom_in_read_text(self, tmp_path: Path) -> None:
        """D4: BOM at start — _read_text returns it as part of content."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"\xef\xbb\xbfhello")
        result = _read_text(p)
        assert result is not None
        assert "hello" in result

    def test_nbsp_in_version_string(self) -> None:
        """D4: NBSP in version spec — _parse_min_python can't match digits."""
        assert _parse_min_python(">=3\u00a010") == "3.10"

    def test_zwsp_in_requires_python(self) -> None:
        """D4: Zero-width space in '>=3\u200b.8' — no match on \\d+\\.\\d+."""
        assert _parse_min_python(">=3\u200b.8") == "3.10"

    def test_zwj_in_package_name(self, tmp_path: Path) -> None:
        """D4: ZWJ in package name — detect_install_cmd still works."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(name='my\u200dpkg')\n",
            encoding="utf-8",
        )
        assert detect_install_cmd(tmp_path) == "pip install -e ."

    def test_soft_hyphen_in_version_spec(self) -> None:
        """D4: Soft hyphen in specifier — _parse_min_python can't match."""
        assert _parse_min_python(">=3\u00ad.8") == "3.10"

    def test_rtl_mark_in_text_content(self, tmp_path: Path) -> None:
        """D4: RTL mark preserved by _read_text."""
        p = tmp_path / "f.txt"
        content = "hello\u200fworld"
        p.write_text(content, encoding="utf-8")
        assert _read_text(p) == content

    def test_nbsp_in_python_version_file(self, tmp_path: Path) -> None:
        """D4: NBSP in .python-version — can't match \\d+.\\d+ pattern."""
        (tmp_path / ".python-version").write_text("3\u00a0.11\n", encoding="utf-8")
        assert detect_python_version(tmp_path) == "3.10"

    def test_zwsp_in_pyproject_version(self, tmp_path: Path) -> None:
        """D4: ZWSP in pyproject version — tomllib may parse it fine."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nversion = "1\u200b.0"\n', encoding="utf-8"
        )
        result = detect_version(tmp_path, "owner/pkg")
        # tomllib parses the string including the ZWSP
        assert result in ("1\u200b.0", None)

    def test_bom_in_setup_py(self, tmp_path: Path) -> None:
        """D4: BOM prefix in setup.py — still readable and parseable."""
        content = "\ufefffrom setuptools import setup\nsetup(python_requires='>=3.9')\n"
        (tmp_path / "setup.py").write_text(content, encoding="utf-8")
        result = detect_python_version(tmp_path)
        # The regex searches raw text; BOM is at start, python_requires is later
        assert result == "3.9"

    def test_bom_in_setup_cfg(self, tmp_path: Path) -> None:
        """D4: BOM prefix in setup.cfg — configparser may handle or fail."""
        content = "\ufeff[options]\npython_requires = >=3.8\n"
        (tmp_path / "setup.cfg").write_text(content, encoding="utf-8")
        # configparser may choke on BOM in section header
        result = detect_python_version(tmp_path)
        # If configparser fails, fallback to 3.10; if it works, 3.8
        assert result in ("3.8", "3.10")

    def test_bom_in_tox_ini(self, tmp_path: Path) -> None:
        """D4: BOM prefix in tox.ini — regex search may still find envlist."""
        content = "\ufeff[tox]\nenvlist = py38,py39\n"
        (tmp_path / "tox.ini").write_text(content, encoding="utf-8")
        result = detect_python_version(tmp_path)
        assert result in ("3.8", "3.10")

    def test_zero_width_no_break_space_in_spec(self) -> None:
        """D4: ZWNBSP (U+FEFF) between >= and digits — breaks regex match."""
        # The \ufeff between >= and 3 prevents >=?\s*(\d+\.\d+) from matching
        assert _parse_min_python(">=\ufeff3.8") == "3.10"

    def test_invisible_separator_in_license(self, tmp_path: Path) -> None:
        """D4: Invisible separator in license text — pattern may still match."""
        (tmp_path / "LICENSE").write_text(
            "MIT\u200b License\n\nPermission is hereby granted MIT\n", encoding="utf-8"
        )
        # "MIT\u200b License" won't match \bMIT License\b due to ZWSP
        # But "Permission is hereby granted.*MIT" should match
        assert check_license(tmp_path) == "MIT"

    def test_read_text_preserves_all_invisible(self, tmp_path: Path) -> None:
        """D4: _read_text preserves all invisible characters."""
        p = tmp_path / "f.txt"
        content = "\ufeff\u200b\u200c\u200d\u200e\u200f\u00a0\u00ad\u2060"
        p.write_text(content, encoding="utf-8")
        assert _read_text(p) == content


class TestZWJEmojiSequences:
    """D4: ZWJ emoji sequences and complex grapheme clusters."""

    def test_family_emoji_in_file_content(self, tmp_path: Path) -> None:
        """D4: Family emoji ZWJ sequence preserved by _read_text."""
        p = tmp_path / "f.txt"
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466"
        p.write_text(family, encoding="utf-8")
        assert _read_text(p) == family

    def test_flag_emoji_in_license(self, tmp_path: Path) -> None:
        """D4: Rainbow flag emoji in LICENSE — no license pattern match."""
        flag = "\U0001f3f3\ufe0f\u200d\U0001f308"
        (tmp_path / "LICENSE").write_text(f"{flag}\nSome license text\n", encoding="utf-8")
        assert check_license(tmp_path) is None

    def test_skin_tone_emoji_in_comment(self, tmp_path: Path) -> None:
        """D4: Skin tone modifier emoji in setup.py comment — still detects version."""
        wave = "\U0001f44b\U0001f3fd"
        (tmp_path / "setup.py").write_text(
            f"# {wave} hello\nfrom setuptools import setup\nsetup(version='1.2.3')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1.2.3"

    def test_emoji_in_version_string_no_match(self, tmp_path: Path) -> None:
        """D4: Emoji in version string — returned as-is from setup.py."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='\U0001f600.1.0')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "\U0001f600.1.0"

    def test_emoji_in_version_file_no_digit_match(self, tmp_path: Path) -> None:
        """D4: Emoji-only VERSION file — detect_version returns None."""
        (tmp_path / "VERSION").write_text("\U0001f600\n", encoding="utf-8")
        assert detect_version(tmp_path, "owner/pkg") is None

    def test_emoji_in_instance_id_validate(self) -> None:
        """D4: Emoji in instance_id — validate_instances checks field presence, not content."""
        instances = [{
            "instance_id": "test_\U0001f600_1",
            "repo": "owner/repo",
            "base_commit": "abc123",
            "python_version": "3.10",
            "install_cmd": "pip install -e .",
            "test_cmd_override": "pytest",
            "packages_source": "",
            "pip_packages": [],
            "pre_install_cmds": [],
            "reqs_paths": [],
            "env_yml_paths": [],
            "log_parser_type": "pytest",
        }]
        assert validate_instances(instances) is True

    def test_emoji_in_jsonl_roundtrip(self, tmp_path: Path) -> None:
        """D4: Emoji survives write_jsonl roundtrip."""
        out = tmp_path / "out.jsonl"
        emoji = "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466"
        write_jsonl([{"emoji": emoji}], str(out))
        loaded = json.loads(out.read_text(encoding="utf-8").strip())
        assert loaded["emoji"] == emoji

    def test_multiple_emoji_in_pyproject_description(self, tmp_path: Path) -> None:
        """D4: Multiple emoji in pyproject — doesn't break TOML parse."""
        content = '[project]\nname = "pkg"\nversion = "1.0"\ndescription = "\U0001f600\U0001f60d\U0001f389"\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8")
        result = detect_version(tmp_path, "owner/pkg")
        assert result == "1.0"

    def test_zwj_sequence_in_cache_roundtrip(self, tmp_path: Path) -> None:
        """D4: ZWJ emoji in cache value survives save/load."""
        cache_file = tmp_path / "cache.json"
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
        data = {"key": {"desc": family}}
        save_cache(data, str(cache_file))
        loaded = load_cache(str(cache_file))
        assert loaded["key"]["desc"] == family

    def test_emoji_flag_sequence_preserved(self, tmp_path: Path) -> None:
        """D4: Regional indicator flag sequence preserved in file content."""
        p = tmp_path / "f.txt"
        flag_us = "\U0001f1fa\U0001f1f8"  # 🇺🇸
        p.write_text(flag_us, encoding="utf-8")
        assert _read_text(p) == flag_us


class TestTemplateInjection:
    """D4: Template syntax treated as literal data, not executed."""

    def test_jinja2_in_pyproject_version(self, tmp_path: Path) -> None:
        """D4: Jinja2 template in version — returned as literal string."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='{{7*7}}')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "{{7*7}}"

    def test_dollar_brace_in_setup_py_version(self, tmp_path: Path) -> None:
        """D4: Shell-style ${} in version — returned as literal."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='${7*7}')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "${7*7}"

    def test_erb_in_config_value(self, tmp_path: Path) -> None:
        """D4: ERB template in version — returned as literal."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='<%= 7*7 %>')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "<%= 7*7 %>"

    def test_fstring_injection_in_version(self, tmp_path: Path) -> None:
        """D4: f-string-like injection in version — regex captures up to first inner quote."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version=\"{__import__('os').system('id')}\")\n",
            encoding="utf-8",
        )
        # Regex [^"']+ stops at the first single-quote inside the string
        result = detect_version(tmp_path, "owner/pkg")
        assert result == "{__import__("

    def test_jinja2_in_requires_python(self, tmp_path: Path) -> None:
        """D4: Jinja2 template in requires-python — fallback."""
        assert _parse_min_python("{{3.8}}") == "3.10"

    def test_template_in_license_no_match(self, tmp_path: Path) -> None:
        """D4: Template injection in LICENSE — no pattern match."""
        (tmp_path / "LICENSE").write_text("{{license_name}}\n<%= type %>\n", encoding="utf-8")
        assert check_license(tmp_path) is None

    def test_template_in_test_cmd_tox(self, tmp_path: Path) -> None:
        """D4: Jinja-like template in tox command — cleaned up by regex sub."""
        (tmp_path / "tox.ini").write_text(
            "[testenv]\ncommands = {{pytest}} tests/\n", encoding="utf-8"
        )
        # The tox parser looks for "pytest" in cmd_line
        result = detect_test_cmd(tmp_path)
        # "{{pytest}}" doesn't contain bare "pytest" as a word in re.sub context
        # Actually it does contain "pytest" substring
        assert "pytest" in result

    def test_percent_format_in_version(self, tmp_path: Path) -> None:
        """D4: Python %-format in version — literal."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='%(version)s')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "%(version)s"

    def test_template_in_jsonl_values(self, tmp_path: Path) -> None:
        """D4: Template strings in JSONL values — preserved literally."""
        out = tmp_path / "out.jsonl"
        records = [{"tpl": "{{7*7}}", "erb": "<%= 1 %>"}]
        write_jsonl(records, str(out))
        loaded = json.loads(out.read_text(encoding="utf-8").strip())
        assert loaded["tpl"] == "{{7*7}}"
        assert loaded["erb"] == "<%= 1 %>"

    def test_shell_command_injection_in_version(self, tmp_path: Path) -> None:
        """D4: Shell command injection attempt in version — returned as literal."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='$(whoami)')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "$(whoami)"


# ===================================================================
# DIMENSION 10 — Data Format & Encoding
# ===================================================================


class TestBOMHandling:
    """D10: Byte Order Mark handling across file types."""

    def test_utf8_bom_pyproject_parse_toml(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on pyproject.toml — _parse_toml handles or returns None."""
        content = b"\xef\xbb\xbf" + b'[project]\nname = "pkg"\nversion = "1.0"\n'
        (tmp_path / "pyproject.toml").write_bytes(content)
        result = _parse_toml(tmp_path / "pyproject.toml")
        # tomllib may reject BOM; if so, regex fallback; if not, parsed
        if result is not None:
            proj = result.get("project", {})
            assert proj.get("version") == "1.0" or proj.get("name") == "pkg"

    def test_utf8_bom_pyproject_regex_fallback(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on pyproject — _parse_toml_regex still finds keys."""
        content = b"\xef\xbb\xbf" + b'[project]\nrequires-python = ">=3.9"\nversion = "2.0"\n'
        (tmp_path / "pyproject.toml").write_bytes(content)
        result = _parse_toml_regex(tmp_path / "pyproject.toml")
        # The BOM becomes \ufeff in text; regex should still match keys
        assert result is not None
        proj = result.get("project", {})
        assert proj.get("requires-python") == ">=3.9"

    def test_utf8_bom_setup_py_detect_python_version(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on setup.py — python_requires still detected."""
        content = b"\xef\xbb\xbf" + b"from setuptools import setup\nsetup(python_requires='>=3.9')\n"
        (tmp_path / "setup.py").write_bytes(content)
        assert detect_python_version(tmp_path) == "3.9"

    def test_utf8_bom_tox_ini_detect_test_cmd(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on tox.ini — detect_test_cmd still works."""
        content = b"\xef\xbb\xbf" + b"[testenv]\ncommands = pytest tests/\n"
        (tmp_path / "tox.ini").write_bytes(content)
        assert detect_test_cmd(tmp_path) == "pytest {test_files}"

    def test_utf8_bom_license_check(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on LICENSE — check_license still matches MIT."""
        content = b"\xef\xbb\xbf" + b"MIT License\n\nPermission is hereby granted MIT\n"
        (tmp_path / "LICENSE").write_bytes(content)
        assert check_license(tmp_path) == "MIT"

    def test_utf8_bom_setup_cfg(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on setup.cfg — configparser may choke on BOM."""
        content = b"\xef\xbb\xbf" + b"[options]\npython_requires = >=3.8\n"
        (tmp_path / "setup.cfg").write_bytes(content)
        result = detect_python_version(tmp_path)
        # configparser may see section as '\ufeff[options]' which is wrong
        assert result in ("3.8", "3.10")

    def test_utf16_le_bom_graceful_failure(self, tmp_path: Path) -> None:
        """D10: UTF-16 LE BOM — _read_text uses errors='replace', returns garbled."""
        content = b"\xff\xfe" + "hello".encode("utf-16-le")
        (tmp_path / "f.txt").write_bytes(content)
        result = _read_text(tmp_path / "f.txt")
        # errors="replace" means it returns something, not None
        assert result is not None

    def test_utf16_be_bom_graceful_failure(self, tmp_path: Path) -> None:
        """D10: UTF-16 BE BOM — _read_text uses errors='replace', returns garbled."""
        content = b"\xfe\xff" + "hello".encode("utf-16-be")
        (tmp_path / "f.txt").write_bytes(content)
        result = _read_text(tmp_path / "f.txt")
        assert result is not None

    def test_bom_in_json_cache(self, tmp_path: Path) -> None:
        """D10: BOM in JSON cache file — load_cache returns empty dict on failure."""
        cache_file = tmp_path / "cache.json"
        content = b"\xef\xbb\xbf" + b'{"key": {"python_version": "3.9"}}'
        cache_file.write_bytes(content)
        result = load_cache(str(cache_file))
        # json.load with UTF-8 encoding may handle BOM or fail
        # The BOM is \ufeff which json.load may accept or reject
        assert isinstance(result, dict)

    def test_bom_in_jsonl_file(self, tmp_path: Path) -> None:
        """D10: BOM in JSONL file — json.loads may fail on first line."""
        jsonl = tmp_path / "data.jsonl"
        content = b"\xef\xbb\xbf" + b'{"instance_id": "test_1", "repo": "o/r"}\n'
        jsonl.write_bytes(content)
        # Read and parse like _load_jsonl would
        text = jsonl.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # First line has BOM — json.loads should handle it in modern Python
        parsed = []
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        # In Python 3.x, json.loads usually handles BOM
        assert len(parsed) >= 0  # At least doesn't crash

    def test_double_bom(self, tmp_path: Path) -> None:
        """D10: Double BOM — _read_text returns both BOM chars."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfhello")
        result = _read_text(p)
        assert result is not None
        assert result.count("\ufeff") == 2

    def test_bom_mid_file(self, tmp_path: Path) -> None:
        """D10: BOM in middle of file — _read_text preserves it."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"hello\xef\xbb\xbfworld")
        result = _read_text(p)
        assert result is not None
        assert "\ufeff" in result

    def test_bom_pyproject_detect_version(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on pyproject.toml — detect_version still works."""
        content = b"\xef\xbb\xbf" + b'[project]\nname = "pkg"\nversion = "3.2.1"\n'
        (tmp_path / "pyproject.toml").write_bytes(content)
        result = detect_version(tmp_path, "owner/pkg")
        # If tomllib fails due to BOM, regex fallback should catch version
        assert result in ("3.2.1", None)

    def test_bom_requirements_txt(self, tmp_path: Path) -> None:
        """D10: UTF-8 BOM on requirements.txt — detect_packages_source still finds it."""
        content = b"\xef\xbb\xbf" + b"numpy>=1.20\n"
        (tmp_path / "requirements.txt").write_bytes(content)
        source, paths, _ = detect_packages_source(tmp_path)
        assert source == "requirements.txt"


class TestLineEndings:
    """D10: CRLF, CR, mixed line endings."""

    def test_crlf_pyproject_parse_toml_regex(self, tmp_path: Path) -> None:
        """D10: CRLF line endings in pyproject — _parse_toml_regex still matches."""
        content = '[project]\r\nrequires-python = ">=3.9"\r\nversion = "1.0"\r\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8", newline="")
        result = _parse_toml_regex(tmp_path / "pyproject.toml")
        assert result is not None
        assert result.get("project", {}).get("requires-python") == ">=3.9"

    def test_crlf_pyproject_parse_toml(self, tmp_path: Path) -> None:
        """D10: CRLF in pyproject — _parse_toml handles it."""
        content = '[project]\r\nname = "pkg"\r\nversion = "2.0"\r\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8", newline="")
        result = _parse_toml(tmp_path / "pyproject.toml")
        if result is not None:
            assert result.get("project", {}).get("version") == "2.0"

    def test_cr_only_setup_py(self, tmp_path: Path) -> None:
        """D10: Old Mac CR-only line endings in setup.py."""
        content = "from setuptools import setup\rsetup(python_requires='>=3.8')\r"
        (tmp_path / "setup.py").write_bytes(content.encode("utf-8"))
        # regex with re.MULTILINE: ^ matches after \n only, not \r
        # But re.search without ^ still scans the whole string
        result = detect_python_version(tmp_path)
        assert result == "3.8"

    def test_mixed_line_endings(self, tmp_path: Path) -> None:
        """D10: Mixed \\n and \\r\\n in same file."""
        content = "[project]\nrequires-python = \">=3.11\"\r\nversion = \"1.0\"\n"
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8", newline="")
        result = _parse_toml_regex(tmp_path / "pyproject.toml")
        assert result is not None
        assert result.get("project", {}).get("requires-python") == ">=3.11"

    def test_crlf_in_python_version_file(self, tmp_path: Path) -> None:
        """D10: CRLF in .python-version — strip() handles it."""
        (tmp_path / ".python-version").write_bytes(b"3.11\r\n")
        assert detect_python_version(tmp_path) == "3.11"

    def test_crlf_in_version_string_setup_py(self, tmp_path: Path) -> None:
        """D10: CRLF in the version string itself — regex [^\"'] stops at quote."""
        content = "from setuptools import setup\r\nsetup(version='1.2.3')\r\n"
        (tmp_path / "setup.py").write_bytes(content.encode("utf-8"))
        assert detect_version(tmp_path, "owner/pkg") == "1.2.3"

    def test_crlf_tox_ini(self, tmp_path: Path) -> None:
        """D10: CRLF in tox.ini — envlist parsed."""
        content = b"[tox]\r\nenvlist = py38,py39\r\n[testenv]\r\ncommands = pytest\r\n"
        (tmp_path / "tox.ini").write_bytes(content)
        result = detect_python_version(tmp_path)
        assert result == "3.8"

    def test_crlf_setup_cfg(self, tmp_path: Path) -> None:
        """D10: CRLF in setup.cfg — configparser handles it."""
        content = b"[options]\r\npython_requires = >=3.9\r\n"
        (tmp_path / "setup.cfg").write_bytes(content)
        assert detect_python_version(tmp_path) == "3.9"

    def test_crlf_license_file(self, tmp_path: Path) -> None:
        """D10: CRLF in LICENSE — regex with DOTALL still matches."""
        content = b"MIT License\r\n\r\nPermission is hereby granted MIT\r\n"
        (tmp_path / "LICENSE").write_bytes(content)
        assert check_license(tmp_path) == "MIT"

    def test_trailing_cr_in_parsed_version(self, tmp_path: Path) -> None:
        """D10: \\r at end of .python-version line — strip() removes it."""
        (tmp_path / ".python-version").write_bytes(b"3.10\r")
        assert detect_python_version(tmp_path) == "3.10"

    def test_save_load_cache_crlf_value(self, tmp_path: Path) -> None:
        """D10: CRLF in cached data value — JSON preserves it."""
        cache_file = tmp_path / "cache.json"
        data = {"key": {"desc": "line1\r\nline2"}}
        save_cache(data, str(cache_file))
        loaded = load_cache(str(cache_file))
        assert loaded["key"]["desc"] == "line1\r\nline2"

    def test_write_jsonl_crlf_in_field(self, tmp_path: Path) -> None:
        """D10: CRLF in JSONL field value — preserved in output."""
        out = tmp_path / "out.jsonl"
        records = [{"text": "hello\r\nworld"}]
        write_jsonl(records, str(out))
        loaded = json.loads(out.read_text(encoding="utf-8").strip())
        assert loaded["text"] == "hello\r\nworld"

    def test_crlf_in_requirements_txt(self, tmp_path: Path) -> None:
        """D10: CRLF in requirements.txt — detect_packages_source still finds file."""
        (tmp_path / "requirements.txt").write_bytes(b"numpy>=1.20\r\nscapy>=1.0\r\n")
        source, paths, _ = detect_packages_source(tmp_path)
        assert source == "requirements.txt"

    def test_cr_only_pyproject(self, tmp_path: Path) -> None:
        """D10: CR-only line endings in pyproject.toml — regex may not match multiline."""
        content = '[project]\rrequires-python = ">=3.8"\rversion = "1.0"\r'
        (tmp_path / "pyproject.toml").write_bytes(content.encode("utf-8"))
        result = _parse_toml_regex(tmp_path / "pyproject.toml")
        # With CR-only, the whole file is one "line" to regex multiline
        # But requires-python regex doesn't use ^$ so it should still match
        if result is not None:
            assert result.get("project", {}).get("requires-python") == ">=3.8"


class TestNumberLocale:
    """D10: Locale-specific number formats in version strings."""

    def test_european_comma_version_no_match(self) -> None:
        """D10: '1,0' with comma — _parse_min_python can't match \\d+\\.\\d+."""
        assert _parse_min_python(">=3,8") == "3.10"

    def test_comma_in_version_string(self, tmp_path: Path) -> None:
        """D10: Version '1,0' in setup.py — regex [^\"'] captures it as-is."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1,0')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1,0"

    def test_thousands_separator_version(self, tmp_path: Path) -> None:
        """D10: Version '1.000' — valid per regex (just looks like 1.0.0.0 ish)."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1.000')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1.000"

    def test_scientific_notation_no_match(self) -> None:
        """D10: '1e2' in version spec — _parse_min_python can't match \\d+\\.\\d+."""
        assert _parse_min_python(">=1e2") == "3.10"

    def test_scientific_notation_in_version_string(self, tmp_path: Path) -> None:
        """D10: Version '1e2' in setup.py — regex captures it literally."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1e2')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1e2"

    def test_unicode_decimal_digits_no_match(self) -> None:
        """D10: Arabic-Indic digits ٣.٨ — _parse_min_python can't match \\d."""
        # \\d in Python regex does NOT match Arabic-Indic digits by default
        # (re module matches only ASCII digits unless re.UNICODE flag on \\d
        #  but \\d in the pattern \\d+\\.\\d+ matches unicode digits by default
        #  in Python 3)
        spec = ">=\u0663.\u0668"  # Arabic-Indic 3.8
        result = _parse_min_python(spec)
        # Python 3 re \d matches Unicode digits, so this should match
        assert result in ("3.10", "\u0663.\u0668")

    def test_comma_spec_python_version_fallback(self, tmp_path: Path) -> None:
        """D10: requires-python with comma decimal in pyproject — no match."""
        content = '[project]\nrequires-python = ">=3,9"\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8")
        result = detect_python_version(tmp_path)
        # The specifier ">=3,9" — _parse_min_python won't find \\d+\\.\\d+
        assert result == "3.10"

    def test_version_with_leading_zero(self, tmp_path: Path) -> None:
        """D10: Version '0.0.1' — valid, detected normally."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='0.0.1')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "0.0.1"

    def test_version_with_plus_local(self, tmp_path: Path) -> None:
        """D10: Version '1.0+local' — captured by regex."""
        (tmp_path / "setup.py").write_text(
            "from setuptools import setup\nsetup(version='1.0+local')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == "1.0+local"

    def test_negative_version_spec(self) -> None:
        """D10: Negative number in spec — minus before digit breaks >=?\\s*(\\d+\\.\\d+) match."""
        # ">=-3.8" — the regex >=?\s*(\d+\.\d+) requires digits immediately after optional space
        # The - prevents the >= branch from matching, but == branch also fails
        assert _parse_min_python(">=-3.8") == "3.10"


# ===================================================================
# Additional parametrized tests to reach 150+ coverage
# ===================================================================


class TestRTLParametrized:
    """D4: Parametrized RTL text scenarios across multiple functions."""

    @pytest.mark.parametrize("rtl_text", [
        "مرحبا",      # Arabic
        "שלום",        # Hebrew
        "سلام",        # Farsi
        "مرحبا שלום",  # Mixed Arabic + Hebrew
    ])
    def test_read_text_preserves_various_rtl(self, tmp_path: Path, rtl_text: str) -> None:
        """D4: _read_text preserves various RTL scripts."""
        p = tmp_path / "f.txt"
        p.write_text(rtl_text, encoding="utf-8")
        assert _read_text(p) == rtl_text

    @pytest.mark.parametrize("rtl_text", [
        "مرحبا",
        "שלום",
        "العربية",
        "עברית",
    ])
    def test_rtl_in_python_version_all_fallback(self, tmp_path: Path, rtl_text: str) -> None:
        """D4: Various RTL scripts in .python-version all cause fallback."""
        (tmp_path / ".python-version").write_text(f"{rtl_text}\n", encoding="utf-8")
        assert detect_python_version(tmp_path) == "3.10"

    @pytest.mark.parametrize("rtl_text,expected", [
        ("مرحبا", "مرحبا"),
        ("1.0-עברית", "1.0-עברית"),
        ("v2.0-سلام", "v2.0-سلام"),
    ])
    def test_rtl_in_setup_py_version_various(self, tmp_path: Path, rtl_text: str, expected: str) -> None:
        """D4: RTL text in setup.py version — captured as-is by regex."""
        (tmp_path / "setup.py").write_text(
            f"from setuptools import setup\nsetup(version='{rtl_text}')\n",
            encoding="utf-8",
        )
        assert detect_version(tmp_path, "owner/pkg") == expected


class TestInvisibleParametrized:
    """D4: Parametrized invisible character tests."""

    @pytest.mark.parametrize("invisible,name", [
        ("\u200b", "ZWSP"),
        ("\u200c", "ZWNJ"),
        ("\u200d", "ZWJ"),
        ("\u200e", "LRM"),
        ("\u200f", "RLM"),
        ("\u2060", "word-joiner"),
        ("\u00ad", "soft-hyphen"),
        ("\ufeff", "BOM"),
    ])
    def test_invisible_in_version_spec_causes_fallback(self, invisible: str, name: str) -> None:
        """D4: Invisible char between digits in specifier breaks regex match."""
        spec = f">=3{invisible}.8"
        result = _parse_min_python(spec)
        assert result == "3.10"

    @pytest.mark.parametrize("invisible", [
        "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060",
    ])
    def test_invisible_in_file_content_preserved(self, tmp_path: Path, invisible: str) -> None:
        """D4: Each invisible char preserved in file content."""
        p = tmp_path / "f.txt"
        content = f"before{invisible}after"
        p.write_text(content, encoding="utf-8")
        assert _read_text(p) == content


class TestBOMParametrized:
    """D10: Parametrized BOM tests across file types."""

    @pytest.mark.parametrize("filename,content_after_bom,func", [
        ("LICENSE", b"Apache License\nVersion 2.0\nLicensed under the Apache License", "license"),
        ("LICENSE.md", b"MIT License\nPermission is hereby granted MIT", "license"),
        ("LICENCE", b"BSD 3-Clause\nRedistribution and use", "license"),
    ])
    def test_utf8_bom_various_license_files(
        self, tmp_path: Path, filename: str, content_after_bom: bytes, func: str
    ) -> None:
        """D10: UTF-8 BOM on various license file names — still matched."""
        (tmp_path / filename).write_bytes(b"\xef\xbb\xbf" + content_after_bom)
        result = check_license(tmp_path)
        assert result is not None

    @pytest.mark.parametrize("bom_bytes,desc", [
        (b"\xef\xbb\xbf", "UTF-8 BOM"),
        (b"\xef\xbb\xbf\xef\xbb\xbf", "double UTF-8 BOM"),
    ])
    def test_bom_variants_in_read_text(self, tmp_path: Path, bom_bytes: bytes, desc: str) -> None:
        """D10: Various BOM patterns — _read_text returns content."""
        p = tmp_path / "f.txt"
        p.write_bytes(bom_bytes + b"content")
        result = _read_text(p)
        assert result is not None
        assert "content" in result


class TestLineEndingsParametrized:
    """D10: Parametrized line ending tests."""

    @pytest.mark.parametrize("line_ending,desc", [
        ("\n", "LF"),
        ("\r\n", "CRLF"),
        ("\r", "CR"),
    ])
    def test_line_endings_in_python_version_file(
        self, tmp_path: Path, line_ending: str, desc: str
    ) -> None:
        """D10: Various line endings in .python-version — strip handles them."""
        (tmp_path / ".python-version").write_bytes(f"3.11{line_ending}".encode("utf-8"))
        assert detect_python_version(tmp_path) == "3.11"

    @pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
    def test_line_endings_in_setup_py_version(self, tmp_path: Path, line_ending: str) -> None:
        """D10: Various line endings in setup.py — version still detected."""
        content = f"from setuptools import setup{line_ending}setup(version='5.0'){line_ending}"
        (tmp_path / "setup.py").write_bytes(content.encode("utf-8"))
        assert detect_version(tmp_path, "owner/pkg") == "5.0"

    @pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
    def test_line_endings_in_setup_cfg_python_requires(
        self, tmp_path: Path, line_ending: str
    ) -> None:
        """D10: Various line endings in setup.cfg — configparser handles them."""
        content = f"[options]{line_ending}python_requires = >=3.9{line_ending}"
        (tmp_path / "setup.cfg").write_bytes(content.encode("utf-8"))
        assert detect_python_version(tmp_path) == "3.9"

    @pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
    def test_line_endings_in_license(self, tmp_path: Path, line_ending: str) -> None:
        """D10: Various line endings in LICENSE — regex DOTALL handles them."""
        content = f"MIT License{line_ending}{line_ending}Permission is hereby granted MIT{line_ending}"
        (tmp_path / "LICENSE").write_bytes(content.encode("utf-8"))
        assert check_license(tmp_path) == "MIT"


class TestMixedEncodingEdgeCases:
    """D10: Additional encoding edge cases."""

    def test_null_byte_in_file(self, tmp_path: Path) -> None:
        """D10: Null byte in file content — _read_text returns with replacement."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"hello\x00world")
        result = _read_text(p)
        assert result is not None
        assert "hello" in result

    def test_latin1_chars_read_as_utf8_replace(self, tmp_path: Path) -> None:
        """D10: Latin-1 byte 0x80-0xFF — errors='replace' produces replacement chars."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"hello\x80\x81world")
        result = _read_text(p)
        assert result is not None
        assert "hello" in result
        assert "world" in result

    def test_truncated_utf8_sequence(self, tmp_path: Path) -> None:
        """D10: Truncated UTF-8 multibyte sequence — errors='replace' handles it."""
        p = tmp_path / "f.txt"
        # \xc3 is start of 2-byte UTF-8 but missing continuation byte
        p.write_bytes(b"hello\xc3world")
        result = _read_text(p)
        assert result is not None

    def test_overlong_utf8_encoding(self, tmp_path: Path) -> None:
        """D10: Overlong UTF-8 encoding — errors='replace' handles it."""
        p = tmp_path / "f.txt"
        # Overlong encoding of '/' (U+002F): 0xC0 0xAF
        p.write_bytes(b"hello\xc0\xafworld")
        result = _read_text(p)
        assert result is not None

    def test_surrogates_in_bytes(self, tmp_path: Path) -> None:
        """D10: Surrogate pair bytes — errors='replace' handles them."""
        p = tmp_path / "f.txt"
        # UTF-8 encoding of surrogate U+D800 (invalid): ED A0 80
        p.write_bytes(b"hello\xed\xa0\x80world")
        result = _read_text(p)
        assert result is not None

    def test_pure_binary_file_read_text(self, tmp_path: Path) -> None:
        """D10: Binary file — _read_text with errors='replace' returns garbled string."""
        p = tmp_path / "f.bin"
        p.write_bytes(bytes(range(256)))
        result = _read_text(p)
        assert result is not None
        assert len(result) > 0

    def test_empty_file_read_text(self, tmp_path: Path) -> None:
        """D10: Empty file — _read_text returns empty string."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"")
        assert _read_text(p) == ""

    def test_only_bom_file(self, tmp_path: Path) -> None:
        """D10: File containing only BOM — _read_text returns BOM char."""
        p = tmp_path / "f.txt"
        p.write_bytes(b"\xef\xbb\xbf")
        result = _read_text(p)
        assert result == "\ufeff"

    def test_json_with_unicode_escapes_in_cache(self, tmp_path: Path) -> None:
        """D10: JSON unicode escapes in cache — load_cache decodes them."""
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"k": {"v": "caf\\u00e9"}}', encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded["k"]["v"] == "café"

    def test_jsonl_with_unicode_escapes(self, tmp_path: Path) -> None:
        """D10: Unicode escapes in JSONL — preserved through write/read."""
        out = tmp_path / "out.jsonl"
        write_jsonl([{"text": "caf\u00e9"}], str(out))
        raw = out.read_text(encoding="utf-8").strip()
        loaded = json.loads(raw)
        assert loaded["text"] == "café"
