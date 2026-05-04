"""End-to-end tests for scripts/detect_repo_specs.py.

Tests the full CLI pipeline: main(), process_repo_group(), license filtering,
dry-run mode, --validate flag, cache roundtrips, and multi-worker execution.

~200 parametrized test cases covering:
  A. process_repo_group  (~40 cases)
  B. main() --validate   (~30 cases)
  C. main() --dry-run    (~30 cases)
  D. main() enrichment   (~40 cases)
  E. license filtering   (~30 cases)
  F. cache roundtrip     (~15 cases)
  G. multi-worker        (~15 cases)
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    REQUIRED_ENRICHMENT_FIELDS,
    load_cache,
    load_instances,
    main,
    process_repo_group,
    save_cache,
    validate_instances,
    write_jsonl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SPECS: dict[str, Any] = {
    "python_version": "3.10",
    "install_cmd": "pip install -e .",
    "test_cmd_override": "pytest {test_files}",
    "packages_source": "",
    "pip_packages": [],
    "pre_install_cmds": [],
    "reqs_paths": [],
    "env_yml_paths": [],
    "log_parser_type": "pytest",
    "version": "1.2.3",
    "_license": "MIT",
}

FAKE_SPECS_BSD: dict[str, Any] = {**FAKE_SPECS, "_license": "BSD-3-Clause"}
FAKE_SPECS_GPL: dict[str, Any] = {**FAKE_SPECS, "_license": "GPL-3.0"}
FAKE_SPECS_NONE: dict[str, Any] = {**FAKE_SPECS, "_license": None}
FAKE_SPECS_APACHE: dict[str, Any] = {**FAKE_SPECS, "_license": "Apache-2.0"}


def _make_instance(
    repo: str = "owner/repo",
    commit: str = "abc123def456",
    instance_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a minimal instance dict."""
    iid = instance_id or f"{repo.replace('/', '__')}__{commit[:8]}_1"
    return {"repo": repo, "instance_id": iid, "base_commit": commit, **extra}


def _write_input_jsonl(path: Path, instances: list[dict[str, Any]]) -> None:
    """Write instances to a JSONL file for CLI consumption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst) + "\n")


def _read_output_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read instances from a JSONL output file."""
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


MODULE = "detect_repo_specs"


# ===========================================================================
# A. process_repo_group (~40 tests)
# ===========================================================================


class TestProcessRepoGroup:
    """Tests for process_repo_group() — clone, checkout, detect, cache."""

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_basic_success(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """Successful clone → checkout → detect returns specs."""
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert result is not None
        assert result["python_version"] == "3.10"
        mock_clone.assert_called_once()
        mock_checkout.assert_called_once()
        mock_detect.assert_called_once()

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_populates_cache(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """Specs are stored in cache dict after detection."""
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert "owner/repo@abc123def456" in cache
        assert cache["owner/repo@abc123def456"] == FAKE_SPECS

    def test_cache_hit_returns_cached(self, tmp_path):
        """If cache already has specs, returns them without cloning."""
        cache = {"owner/repo@abc123": FAKE_SPECS}
        result = process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert result == FAKE_SPECS

    @patch(f"{MODULE}._git_clone", return_value=False)
    def test_clone_failure_returns_none(self, mock_clone, tmp_path):
        """Clone failure → returns None, no checkout attempted."""
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert result is None
        assert "owner/repo@abc123def456" not in cache

    @patch(f"{MODULE}._git_checkout", return_value=False)
    @patch(f"{MODULE}._git_clone", return_value=True)
    def test_checkout_failure_returns_none(self, mock_clone, mock_checkout, tmp_path):
        """Checkout failure → returns None."""
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert result is None

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", side_effect=RuntimeError("boom"))
    def test_detect_exception_returns_none(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """Exception in detect_all_specs → returns None (caught by except)."""
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert result is None

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_dest_path_format(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """dest = clone_dir / repo.replace('/', '__') / commit[:12]."""
        cache: dict[str, Any] = {}
        process_repo_group("numpy/numpy", "deadbeef1234abcd", tmp_path, cache)
        # The clone call should receive the correctly-formatted dest
        call_args = mock_clone.call_args
        dest = call_args[0][1]  # second positional arg
        assert "numpy__numpy" in str(dest)
        assert "deadbeef1234" in str(dest)

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_cleanup_after_success(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """After successful detection, clone dir is cleaned up (finally block)."""
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        # The dest directory should be cleaned up after
        dest = tmp_path / "owner__repo" / "abc123def456"
        assert not dest.exists()

    @patch(f"{MODULE}._git_clone", return_value=False)
    def test_no_cleanup_if_clone_failed(self, mock_clone, tmp_path):
        """If clone failed (cloned=False), no rmtree in finally."""
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        # Should not raise even though no clone dir exists

    # --- Parametrized: different repos and commits ---

    @pytest.mark.parametrize(
        "repo,commit",
        [
            ("numpy/numpy", "a" * 40),
            ("pandas-dev/pandas", "b" * 40),
            ("scipy/scipy", "c" * 40),
            ("scikit-learn/scikit-learn", "d" * 40),
            ("matplotlib/matplotlib", "e" * 40),
            ("pydata/xarray", "f" * 40),
            ("sympy/sympy", "1" * 40),
            ("dask/dask", "2" * 40),
            ("astropy/astropy", "3" * 40),
        ],
        ids=lambda x: x[:20],
    )
    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_all_nine_repos(self, mock_detect, mock_clone, mock_checkout, repo, commit, tmp_path):
        """All 9 benchmark repos can be processed."""
        cache: dict[str, Any] = {}
        result = process_repo_group(repo, commit, tmp_path, cache)
        assert result is not None
        assert f"{repo}@{commit}" in cache

    @pytest.mark.parametrize(
        "commit",
        [
            "a" * 40,
            "0" * 40,
            "abc",  # short commit
            "deadbeef",
            "123456789abcdef0" * 2 + "12345678",
        ],
    )
    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_various_commit_lengths(self, mock_detect, mock_clone, mock_checkout, commit, tmp_path):
        """Different commit hash lengths are handled."""
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", commit, tmp_path, cache)
        assert result is not None

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_existing_dest_is_cleaned_first(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """If dest dir already exists, it's rmtree'd before clone."""
        dest = tmp_path / "owner__repo" / "abc123def456"
        dest.mkdir(parents=True)
        (dest / "stale_file.txt").write_text("old data")
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        # Should succeed without error (stale dir was removed)
        assert "owner/repo@abc123def456" in cache

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs")
    def test_different_specs_per_commit(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """Different commits for same repo get different cache entries."""
        specs_a = {**FAKE_SPECS, "python_version": "3.9"}
        specs_b = {**FAKE_SPECS, "python_version": "3.11"}
        mock_detect.side_effect = [specs_a, specs_b]
        cache: dict[str, Any] = {}
        r1 = process_repo_group("owner/repo", "commit_a", tmp_path, cache)
        r2 = process_repo_group("owner/repo", "commit_b", tmp_path, cache)
        assert r1["python_version"] == "3.9"
        assert r2["python_version"] == "3.11"
        assert len(cache) == 2

    @patch(f"{MODULE}._git_checkout", return_value=True)
    @patch(f"{MODULE}._git_clone", return_value=True)
    @patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS)
    def test_cache_prevents_reclone(self, mock_detect, mock_clone, mock_checkout, tmp_path):
        """Second call with same key uses cache, no clone/checkout."""
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123", tmp_path, cache)
        # Reset mocks
        mock_clone.reset_mock()
        mock_checkout.reset_mock()
        mock_detect.reset_mock()
        # Second call should use cache
        result = process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert result is not None
        mock_clone.assert_not_called()
        mock_checkout.assert_not_called()
        mock_detect.assert_not_called()


# ===========================================================================
# B. main() --validate (~30 tests)
# ===========================================================================


class TestMainValidate:
    """Tests for main() with --validate flag."""

    def _run_validate(self, tmp_path, instances, expect_exit=0):
        """Helper to run main() in validate mode."""
        input_file = tmp_path / "input.jsonl"
        _write_input_jsonl(input_file, instances)
        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(tmp_path / "out.jsonl"),
            "--validate",
        ]
        with patch("sys.argv", args):
            if expect_exit == 0:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0
            else:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    def test_valid_instances_exit_0(self, tmp_path):
        """All instances have required fields → exit 0."""
        inst = _make_instance()
        for f in REQUIRED_ENRICHMENT_FIELDS:
            inst[f] = "value"
        self._run_validate(tmp_path, [inst], expect_exit=0)

    def test_missing_field_exit_1(self, tmp_path):
        """Instance missing a required field → exit 1."""
        inst = _make_instance()
        # Only add some fields, leave out python_version
        for f in REQUIRED_ENRICHMENT_FIELDS:
            if f != "python_version":
                inst[f] = "value"
        self._run_validate(tmp_path, [inst], expect_exit=1)

    @pytest.mark.parametrize("missing_field", list(REQUIRED_ENRICHMENT_FIELDS))
    def test_each_missing_field(self, missing_field, tmp_path):
        """Each individual required field missing → exit 1."""
        inst = _make_instance()
        for f in REQUIRED_ENRICHMENT_FIELDS:
            if f != missing_field:
                inst[f] = "value"
        self._run_validate(tmp_path, [inst], expect_exit=1)

    def test_empty_input_exits_1(self, tmp_path):
        """Empty input file → exit 1 (no instances loaded)."""
        input_file = tmp_path / "input.jsonl"
        input_file.write_text("")
        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(tmp_path / "out.jsonl"),
            "--validate",
        ]
        with patch("sys.argv", args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_multiple_valid_instances(self, tmp_path):
        """Multiple valid instances → exit 0."""
        instances = []
        for i in range(5):
            inst = _make_instance(instance_id=f"inst_{i}")
            for f in REQUIRED_ENRICHMENT_FIELDS:
                inst[f] = f"value_{i}"
            instances.append(inst)
        self._run_validate(tmp_path, instances, expect_exit=0)

    def test_one_bad_among_many(self, tmp_path):
        """One invalid among many valid → exit 1."""
        instances = []
        for i in range(5):
            inst = _make_instance(instance_id=f"inst_{i}")
            for f in REQUIRED_ENRICHMENT_FIELDS:
                inst[f] = f"value_{i}"
            instances.append(inst)
        # Remove a field from the last one
        del instances[-1]["python_version"]
        self._run_validate(tmp_path, instances, expect_exit=1)

    def test_all_fields_empty_string_is_valid(self, tmp_path):
        """Fields present but empty string → still valid (field exists)."""
        inst = _make_instance()
        for f in REQUIRED_ENRICHMENT_FIELDS:
            inst[f] = ""
        self._run_validate(tmp_path, [inst], expect_exit=0)

    def test_all_fields_none_is_valid(self, tmp_path):
        """Fields present but None → still valid (field exists in dict)."""
        inst = _make_instance()
        for f in REQUIRED_ENRICHMENT_FIELDS:
            inst[f] = None
        self._run_validate(tmp_path, [inst], expect_exit=0)

    @pytest.mark.parametrize("count", [1, 2, 5, 10, 50])
    def test_various_instance_counts(self, count, tmp_path):
        """Varying numbers of valid instances all pass."""
        instances = []
        for i in range(count):
            inst = _make_instance(instance_id=f"inst_{i}")
            for f in REQUIRED_ENRICHMENT_FIELDS:
                inst[f] = "v"
            instances.append(inst)
        self._run_validate(tmp_path, instances, expect_exit=0)

    @pytest.mark.parametrize(
        "num_missing",
        [1, 2, 3, 5, len(REQUIRED_ENRICHMENT_FIELDS)],
    )
    def test_varying_missing_count(self, num_missing, tmp_path):
        """Instance missing N fields → exit 1."""
        inst = _make_instance()
        fields = list(REQUIRED_ENRICHMENT_FIELDS)
        for f in fields[num_missing:]:
            inst[f] = "value"
        # First num_missing fields are absent
        self._run_validate(tmp_path, [inst], expect_exit=1)


# ===========================================================================
# C. main() --dry-run (~30 tests)
# ===========================================================================


class TestMainDryRun:
    """Tests for main() with --dry-run flag."""

    def _run_dry(self, tmp_path, instances, extra_args=None, specs=None):
        """Helper to run main() in dry-run mode. Returns (stdout, output_exists)."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, instances)

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--dry-run",
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]
        if extra_args:
            args.extend(extra_args)

        use_specs = specs or FAKE_SPECS
        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", return_value=use_specs),
        ):
            import io
            from contextlib import redirect_stdout
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main()

        return stdout.getvalue(), output_file.exists()

    def test_no_output_file_written(self, tmp_path):
        """Dry-run does not create output JSONL file."""
        inst = _make_instance()
        _, output_exists = self._run_dry(tmp_path, [inst])
        assert not output_exists

    def test_prints_repo_header(self, tmp_path):
        """Dry-run prints repo @ commit header."""
        inst = _make_instance(repo="numpy/numpy", commit="deadbeef12345678")
        stdout, _ = self._run_dry(tmp_path, [inst])
        assert "numpy/numpy" in stdout
        assert "deadbeef" in stdout

    def test_prints_spec_keys(self, tmp_path):
        """Dry-run prints spec key-value pairs."""
        inst = _make_instance()
        stdout, _ = self._run_dry(tmp_path, [inst])
        assert "python_version" in stdout
        assert "install_cmd" in stdout
        assert "test_cmd_override" in stdout

    def test_prints_license_key(self, tmp_path):
        """License is printed with 'license:' label (not '_license:')."""
        inst = _make_instance()
        stdout, _ = self._run_dry(tmp_path, [inst])
        assert "license:" in stdout

    @pytest.mark.parametrize(
        "repo",
        [
            "numpy/numpy",
            "pandas-dev/pandas",
            "scipy/scipy",
            "scikit-learn/scikit-learn",
            "matplotlib/matplotlib",
            "pydata/xarray",
            "sympy/sympy",
            "dask/dask",
            "astropy/astropy",
        ],
    )
    def test_dry_run_each_repo(self, repo, tmp_path):
        """Dry-run works for each of the 9 benchmark repos."""
        inst = _make_instance(repo=repo)
        stdout, output_exists = self._run_dry(tmp_path, [inst])
        assert not output_exists
        assert repo in stdout

    def test_multiple_repos_in_output(self, tmp_path):
        """Multiple repos each get their own section."""
        instances = [
            _make_instance(repo="numpy/numpy", commit="aaa"),
            _make_instance(repo="pandas-dev/pandas", commit="bbb"),
        ]
        stdout, _ = self._run_dry(tmp_path, instances)
        assert "numpy/numpy" in stdout
        assert "pandas-dev/pandas" in stdout

    def test_specs_failure_no_print(self, tmp_path):
        """If process_repo_group returns None, that repo is not printed."""
        inst = _make_instance()
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, [inst])

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--dry-run",
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]
        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", return_value=None),
        ):
            import io
            from contextlib import redirect_stdout
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main()

        assert "python_version" not in stdout.getvalue()

    @pytest.mark.parametrize("pv", ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13"])
    def test_various_python_versions_in_output(self, pv, tmp_path):
        """Different python versions appear in dry-run output."""
        specs = {**FAKE_SPECS, "python_version": pv}
        inst = _make_instance()
        stdout, _ = self._run_dry(tmp_path, [inst], specs=specs)
        assert pv in stdout

    def test_cache_still_saved_in_dry_run(self, tmp_path):
        """Cache file is written even in dry-run mode."""
        inst = _make_instance()
        self._run_dry(tmp_path, [inst])
        cache_file = tmp_path / "cache.json"
        assert cache_file.exists()


# ===========================================================================
# D. main() enrichment flow (~40 tests)
# ===========================================================================


class TestMainEnrichment:
    """Tests for main() enrichment: specs applied to instances, output written."""

    def _run_enrich(
        self,
        tmp_path,
        instances,
        specs=None,
        extra_args=None,
        specs_side_effect=None,
    ) -> list[dict[str, Any]]:
        """Run main() in enrichment mode. Returns output instances."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, instances)

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]
        if extra_args:
            args.extend(extra_args)

        use_specs = specs or FAKE_SPECS
        mock_kwargs = {}
        if specs_side_effect:
            mock_kwargs["side_effect"] = specs_side_effect
        else:
            mock_kwargs["return_value"] = use_specs

        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", **mock_kwargs),
        ):
            main()

        return _read_output_jsonl(output_file)

    def test_enrichment_fields_applied(self, tmp_path):
        """All REQUIRED_ENRICHMENT_FIELDS appear in output instances."""
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst])
        assert len(results) == 1
        for field in REQUIRED_ENRICHMENT_FIELDS:
            assert field in results[0]

    def test_enrichment_values_match_specs(self, tmp_path):
        """Enriched field values match what process_repo_group returned."""
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst])
        for field in REQUIRED_ENRICHMENT_FIELDS:
            assert results[0][field] == FAKE_SPECS[field]

    def test_version_set_if_detected_and_missing(self, tmp_path):
        """version field set from specs when instance lacks it."""
        inst = _make_instance()  # no 'version' key
        results = self._run_enrich(tmp_path, [inst])
        assert results[0]["version"] == "1.2.3"

    def test_version_not_overwritten_if_present(self, tmp_path):
        """version field NOT overwritten if instance already has one."""
        inst = _make_instance(version="0.9.0")
        results = self._run_enrich(tmp_path, [inst])
        assert results[0]["version"] == "0.9.0"

    def test_version_not_set_if_specs_empty(self, tmp_path):
        """version not added when specs return empty/None version."""
        specs = {**FAKE_SPECS, "version": ""}
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst], specs=specs)
        # version should not be set since specs version is falsy
        assert results[0].get("version", "") == ""

    def test_original_fields_preserved(self, tmp_path):
        """Instance's original fields (repo, instance_id, etc.) preserved."""
        inst = _make_instance(repo="numpy/numpy", commit="aaa", extra_field="keep_me")
        results = self._run_enrich(tmp_path, [inst])
        assert results[0]["repo"] == "numpy/numpy"
        assert results[0]["instance_id"] == inst["instance_id"]
        assert results[0]["extra_field"] == "keep_me"

    def test_multiple_instances_same_group(self, tmp_path):
        """Multiple instances sharing same (repo, commit) all get enriched."""
        instances = [
            _make_instance(instance_id="inst_1"),
            _make_instance(instance_id="inst_2"),
            _make_instance(instance_id="inst_3"),
        ]
        results = self._run_enrich(tmp_path, instances)
        assert len(results) == 3
        for r in results:
            assert r["python_version"] == "3.10"

    def test_multiple_groups(self, tmp_path):
        """Instances from different repos get correct specs."""
        instances = [
            _make_instance(repo="numpy/numpy", commit="aaa"),
            _make_instance(repo="pandas-dev/pandas", commit="bbb"),
        ]
        specs_a = {**FAKE_SPECS, "python_version": "3.9"}
        specs_b = {**FAKE_SPECS, "python_version": "3.11"}
        call_count = [0]

        def side_effect(repo, commit, *args, **kwargs):
            call_count[0] += 1
            if repo == "numpy/numpy":
                return specs_a
            return specs_b

        results = self._run_enrich(tmp_path, instances, specs_side_effect=side_effect)
        numpy_results = [r for r in results if r["repo"] == "numpy/numpy"]
        pandas_results = [r for r in results if r["repo"] == "pandas-dev/pandas"]
        assert numpy_results[0]["python_version"] == "3.9"
        assert pandas_results[0]["python_version"] == "3.11"

    def test_failed_group_skipped(self, tmp_path):
        """If process_repo_group returns None, those instances are skipped."""
        instances = [
            _make_instance(repo="good/repo", commit="aaa"),
            _make_instance(repo="bad/repo", commit="bbb"),
        ]

        def side_effect(repo, commit, *args, **kwargs):
            if repo == "bad/repo":
                return None
            return FAKE_SPECS

        results = self._run_enrich(tmp_path, instances, specs_side_effect=side_effect)
        assert len(results) == 1
        assert results[0]["repo"] == "good/repo"

    def test_ungrouped_instances_pass_through(self, tmp_path):
        """Instances missing repo or base_commit are added to output unchanged."""
        instances = [
            _make_instance(),
            {"instance_id": "no_repo", "base_commit": "xyz"},  # missing repo
            {"instance_id": "no_commit", "repo": "owner/repo"},  # missing commit
        ]
        results = self._run_enrich(tmp_path, instances)
        # The grouped instance is enriched, the other two pass through
        ids = [r["instance_id"] for r in results]
        assert "no_repo" in ids
        assert "no_commit" in ids

    def test_output_file_created(self, tmp_path):
        """Output JSONL file is created with correct content."""
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst])
        output_file = tmp_path / "output.jsonl"
        assert output_file.exists()
        assert len(results) >= 1

    def test_output_is_valid_jsonl(self, tmp_path):
        """Every line in output is valid JSON."""
        inst = _make_instance()
        self._run_enrich(tmp_path, [inst])
        output_file = tmp_path / "output.jsonl"
        with open(output_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    json.loads(line)  # Should not raise

    @pytest.mark.parametrize("count", [1, 5, 10, 25, 50])
    def test_various_instance_counts(self, count, tmp_path):
        """Enrichment works for various instance counts."""
        instances = [_make_instance(instance_id=f"inst_{i}") for i in range(count)]
        results = self._run_enrich(tmp_path, instances)
        assert len(results) == count

    @pytest.mark.parametrize(
        "install_cmd",
        [
            "pip install -e .",
            "pip install -e . --no-build-isolation",
            "python setup.py develop",
            "pip install .",
            "flit install",
        ],
    )
    def test_various_install_cmds(self, install_cmd, tmp_path):
        """Different install commands from specs are correctly applied."""
        specs = {**FAKE_SPECS, "install_cmd": install_cmd}
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst], specs=specs)
        assert results[0]["install_cmd"] == install_cmd

    @pytest.mark.parametrize(
        "test_cmd",
        [
            "pytest {test_files}",
            "python -m pytest tests/",
            "python -m django test",
            "python -m sympy.testing.runtests",
            "pytest --tb=short -q",
        ],
    )
    def test_various_test_cmds(self, test_cmd, tmp_path):
        """Different test commands from specs are correctly applied."""
        specs = {**FAKE_SPECS, "test_cmd_override": test_cmd}
        inst = _make_instance()
        results = self._run_enrich(tmp_path, [inst], specs=specs)
        assert results[0]["test_cmd_override"] == test_cmd


# ===========================================================================
# E. License filtering (~30 tests)
# ===========================================================================


class TestLicenseFiltering:
    """Tests for license-based filtering in main()."""

    DEFAULT_LICENSES = ["MIT", "MIT-0", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC"]

    def _run_with_license(
        self,
        tmp_path,
        instances,
        specs_fn,
        license_filter=None,
    ) -> list[dict[str, Any]]:
        """Run main() with specified license filter. Returns output instances."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, instances)

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]
        if license_filter is not None:
            if license_filter:  # non-empty list
                args.extend(["--license-filter"] + license_filter)
            else:
                args.append("--license-filter")  # empty = no filter

        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", side_effect=specs_fn),
        ):
            main()

        if output_file.exists():
            return _read_output_jsonl(output_file)
        return []

    @pytest.mark.parametrize("license_name", DEFAULT_LICENSES)
    def test_default_allowed_licenses(self, license_name, tmp_path):
        """Each default-allowed license passes the filter."""
        specs = {**FAKE_SPECS, "_license": license_name}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs
        )
        assert len(results) == 1

    @pytest.mark.parametrize(
        "license_name",
        ["GPL-3.0", "GPL-2.0", "LGPL-2.1", "AGPL-3.0", "MPL-2.0", "Unlicense",
         "CC-BY-4.0", "WTFPL", "Artistic-2.0", "EUPL-1.2"],
    )
    def test_non_default_licenses_filtered(self, license_name, tmp_path):
        """Non-default licenses are filtered out."""
        specs = {**FAKE_SPECS, "_license": license_name}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs
        )
        assert len(results) == 0

    def test_no_license_filter(self, tmp_path):
        """Empty license filter (--license-filter with no args) = no filtering."""
        specs = {**FAKE_SPECS, "_license": "GPL-3.0"}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs, license_filter=[]
        )
        assert len(results) == 1

    def test_custom_license_filter(self, tmp_path):
        """Custom --license-filter only allows specified licenses."""
        specs = {**FAKE_SPECS, "_license": "MIT"}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs, license_filter=["Apache-2.0"]
        )
        assert len(results) == 0  # MIT not in custom filter

    def test_custom_filter_allows_specified(self, tmp_path):
        """Custom filter passes matching licenses."""
        specs = {**FAKE_SPECS, "_license": "Apache-2.0"}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs, license_filter=["Apache-2.0"]
        )
        assert len(results) == 1

    def test_none_license_filtered(self, tmp_path):
        """None license is filtered out (not in default set)."""
        specs = {**FAKE_SPECS, "_license": None}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs
        )
        assert len(results) == 0

    def test_mixed_licenses(self, tmp_path):
        """Mix of allowed and disallowed licenses: only allowed pass."""
        instances = [
            _make_instance(repo="mit/repo", commit="aaa"),
            _make_instance(repo="gpl/repo", commit="bbb"),
            _make_instance(repo="apache/repo", commit="ccc"),
        ]

        def specs_fn(repo, commit, *a, **kw):
            if repo == "mit/repo":
                return {**FAKE_SPECS, "_license": "MIT"}
            elif repo == "gpl/repo":
                return {**FAKE_SPECS, "_license": "GPL-3.0"}
            else:
                return {**FAKE_SPECS, "_license": "Apache-2.0"}

        results = self._run_with_license(tmp_path, instances, specs_fn)
        repos = [r["repo"] for r in results]
        assert "mit/repo" in repos
        assert "apache/repo" in repos
        assert "gpl/repo" not in repos

    def test_license_filter_per_group(self, tmp_path):
        """All instances in a filtered group are removed."""
        instances = [
            _make_instance(repo="gpl/repo", commit="aaa", instance_id="inst_1"),
            _make_instance(repo="gpl/repo", commit="aaa", instance_id="inst_2"),
            _make_instance(repo="gpl/repo", commit="aaa", instance_id="inst_3"),
        ]
        specs = {**FAKE_SPECS, "_license": "GPL-3.0"}
        results = self._run_with_license(
            tmp_path, instances, lambda *a, **kw: specs
        )
        assert len(results) == 0

    @pytest.mark.parametrize(
        "case_variant,expected_count",
        [
            ("mit", 0),
            ("Mit", 0),
            ("mIt", 0),
            ("MiT", 0),
            ("MIT ", 0),
            ("MIT", 1),
        ],
    )
    def test_license_case_sensitivity(self, case_variant, expected_count, tmp_path):
        """License matching is exact string match (case-sensitive, no strip)."""
        specs = {**FAKE_SPECS, "_license": case_variant}
        inst = _make_instance()
        results = self._run_with_license(
            tmp_path, [inst], lambda *a, **kw: specs
        )
        assert len(results) == expected_count


# ===========================================================================
# F. Cache roundtrip (~15 tests)
# ===========================================================================


class TestCacheRoundtrip:
    """Tests for cache loading, saving, and roundtrip behavior."""

    def test_empty_cache_on_missing_file(self, tmp_path):
        """load_cache with nonexistent file returns empty dict."""
        result = load_cache(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        """save_cache → load_cache returns same data."""
        cache = {"repo@abc123": FAKE_SPECS}
        cache_path = str(tmp_path / "cache.json")
        save_cache(cache, cache_path)
        loaded = load_cache(cache_path)
        assert loaded == cache

    def test_corrupt_cache_returns_empty(self, tmp_path):
        """Corrupt cache file → empty dict returned."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("not valid json {{{", encoding="utf-8")
        result = load_cache(str(cache_path))
        assert result == {}

    def test_cache_grows_across_calls(self, tmp_path):
        """Cache accumulates entries across process_repo_group calls."""
        cache: dict[str, Any] = {}
        with (
            patch(f"{MODULE}._git_checkout", return_value=True),
            patch(f"{MODULE}._git_clone", return_value=True),
            patch(f"{MODULE}.detect_all_specs", return_value=FAKE_SPECS),
        ):
            process_repo_group("repo1", "aaa", tmp_path, cache)
            process_repo_group("repo2", "bbb", tmp_path, cache)
        assert len(cache) == 2

    def test_cache_saved_during_enrichment(self, tmp_path):
        """main() saves cache after processing."""
        inst = _make_instance()
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, [inst])

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]
        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", return_value=FAKE_SPECS),
        ):
            main()

        assert cache_file.exists()

    def test_cache_hit_on_second_run(self, tmp_path):
        """Second run uses cache, process_repo_group sees cache hit."""
        inst = _make_instance()
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, [inst])

        # Pre-populate cache
        cache_data = {"owner/repo@abc123def456": FAKE_SPECS}
        save_cache(cache_data, str(cache_file))

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
        ]

        with patch("sys.argv", args):
            # Don't mock process_repo_group — it should use the real function
            # which will find cache hit
            with patch(f"{MODULE}._git_clone") as mock_clone:
                main()
                # Clone should not be called because cache hit
                mock_clone.assert_not_called()

    def test_empty_cache_file(self, tmp_path):
        """Empty JSON object in cache file → empty dict."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{}", encoding="utf-8")
        result = load_cache(str(cache_path))
        assert result == {}

    @pytest.mark.parametrize("n_entries", [1, 5, 10, 50])
    def test_cache_various_sizes(self, n_entries, tmp_path):
        """Cache roundtrip works for various entry counts."""
        cache = {f"repo_{i}@commit_{i}": FAKE_SPECS for i in range(n_entries)}
        cache_path = str(tmp_path / "cache.json")
        save_cache(cache, cache_path)
        loaded = load_cache(cache_path)
        assert len(loaded) == n_entries

    def test_cache_preserves_all_spec_fields(self, tmp_path):
        """All spec fields survive JSON roundtrip."""
        cache = {"repo@abc": FAKE_SPECS}
        cache_path = str(tmp_path / "cache.json")
        save_cache(cache, cache_path)
        loaded = load_cache(cache_path)
        for key in FAKE_SPECS:
            assert loaded["repo@abc"][key] == FAKE_SPECS[key]

    def test_cache_file_is_valid_json(self, tmp_path):
        """Saved cache file is valid JSON."""
        cache = {"repo@abc": FAKE_SPECS}
        cache_path = tmp_path / "cache.json"
        save_cache(cache, str(cache_path))
        data = json.loads(cache_path.read_text())
        assert isinstance(data, dict)


# ===========================================================================
# G. Multi-worker execution (~15 tests)
# ===========================================================================


class TestMultiWorker:
    """Tests for multi-worker execution in main()."""

    def _run_with_workers(self, tmp_path, instances, workers, specs_fn=None):
        """Run main() with specified worker count. Returns output instances."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        cache_file = tmp_path / "cache.json"
        _write_input_jsonl(input_file, instances)

        args = [
            "detect_repo_specs",
            "--input", str(input_file),
            "--output", str(output_file),
            "--cache-file", str(cache_file),
            "--clone-dir", str(tmp_path / "clones"),
            "--workers", str(workers),
        ]

        fn = specs_fn or (lambda *a, **kw: FAKE_SPECS)
        with (
            patch("sys.argv", args),
            patch(f"{MODULE}.process_repo_group", side_effect=fn),
        ):
            main()

        return _read_output_jsonl(output_file)

    @pytest.mark.parametrize("workers", [1, 2, 4])
    def test_various_worker_counts(self, workers, tmp_path):
        """Results are the same regardless of worker count."""
        instances = [
            _make_instance(repo=f"repo_{i}/project", commit=f"commit_{i}")
            for i in range(4)
        ]
        results = self._run_with_workers(tmp_path, instances, workers)
        assert len(results) == 4

    def test_single_worker_sequential(self, tmp_path):
        """Single worker processes groups sequentially (no ThreadPoolExecutor)."""
        instances = [_make_instance()]
        results = self._run_with_workers(tmp_path, instances, workers=1)
        assert len(results) == 1

    def test_worker_exception_handled(self, tmp_path):
        """Worker exception is caught, other groups still processed."""
        instances = [
            _make_instance(repo="good/repo", commit="aaa"),
            _make_instance(repo="bad/repo", commit="bbb"),
        ]

        def specs_fn(repo, commit, *a, **kw):
            if repo == "bad/repo":
                raise RuntimeError("worker exploded")
            return FAKE_SPECS

        results = self._run_with_workers(tmp_path, instances, workers=2, specs_fn=specs_fn)
        # Only good/repo should be in output
        assert len(results) == 1
        assert results[0]["repo"] == "good/repo"

    def test_multiple_groups_parallel(self, tmp_path):
        """Multiple groups are processed when using multiple workers."""
        instances = [
            _make_instance(repo=f"repo_{i}/proj", commit=f"c{i}")
            for i in range(8)
        ]
        results = self._run_with_workers(tmp_path, instances, workers=4)
        assert len(results) == 8

    @pytest.mark.parametrize("workers", [2, 4, 8])
    def test_workers_more_than_groups(self, workers, tmp_path):
        """More workers than groups doesn't cause issues."""
        instances = [_make_instance()]
        results = self._run_with_workers(tmp_path, instances, workers=workers)
        assert len(results) == 1

    def test_all_workers_fail(self, tmp_path):
        """If all workers fail, output is still written (empty or with ungrouped)."""
        instances = [
            _make_instance(repo="bad1/repo", commit="aaa"),
            _make_instance(repo="bad2/repo", commit="bbb"),
        ]

        def specs_fn(*a, **kw):
            raise RuntimeError("all fail")

        results = self._run_with_workers(tmp_path, instances, workers=2, specs_fn=specs_fn)
        assert len(results) == 0

    def test_same_results_single_vs_multi(self, tmp_path):
        """Single-worker and multi-worker produce same number of results."""
        instances = [
            _make_instance(repo=f"repo_{i}/proj", commit=f"c{i}")
            for i in range(4)
        ]
        r1 = self._run_with_workers(tmp_path / "single", instances, workers=1)
        r2 = self._run_with_workers(tmp_path / "multi", instances, workers=4)
        assert len(r1) == len(r2)
