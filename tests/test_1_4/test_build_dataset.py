"""
Tests for swefficiency.collect.build_dataset

Coverage target: create_instance, is_valid_pull, is_valid_instance, has_test_patch, main
Dimensions: D1 Input Domain, D2 Null/Empty, D3 Type Coercion, D4 String Brutality,
            D5 Time/Date, D6 State/Lifecycle, D8 Error Handling, D9 Security,
            D10 Data Format, D11 Performance, D12 Integration
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from swefficiency.collect.build_dataset import (
    create_instance,
    has_test_patch,
    is_valid_instance,
    is_valid_pull,
    main,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_pull(
    number=1,
    merged_at="2024-01-01T00:00:00Z",
    full_name="owner/repo",
    base_sha="abc123",
    created_at="2024-01-01T00:00:00Z",
    resolved_issues=None,
    body=None,
    title=None,
):
    pull = {
        "number": number,
        "merged_at": merged_at,
        "base": {"sha": base_sha, "repo": {"full_name": full_name}},
        "created_at": created_at,
        "resolved_issues": resolved_issues or [],
        "body": body or "",
        "title": title or "",
    }
    return pull


def _make_instance(
    patch_val="diff --git a/f.py b/f.py",
    test_patch_val="diff --git a/tests/t.py b/tests/t.py",
):
    return {
        "repo": "owner/repo",
        "pull_number": 1,
        "instance_id": "owner__repo-1",
        "issue_numbers": [],
        "base_commit": "abc123",
        "patch": patch_val,
        "test_patch": test_patch_val,
        "problem_statement": "Fix bug",
        "hints_text": "hint",
        "created_at": "2024-01-01T00:00:00Z",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# is_valid_pull — checks pull["merged_at"] is None → False, else True
# Production behavior: ONLY None is invalid. Falsy values 0, "", False are VALID.
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsValidPull:
    # D1: Equivalence classes — merged vs unmerged
    def test_d1_merged_pull_is_valid(self):
        pull = _make_pull(merged_at="2024-01-15T10:30:00Z")
        assert is_valid_pull(pull) is True

    def test_d1_unmerged_pull_none_is_invalid(self):
        pull = _make_pull(merged_at=None)
        assert is_valid_pull(pull) is False

    # D2: Null/Empty/Falsy gauntlet
    def test_d2_empty_string_merged_at_is_valid(self):
        """Empty string is falsy but NOT None — production uses `is None`"""
        pull = _make_pull(merged_at="")
        assert is_valid_pull(pull) is True

    def test_d2_zero_merged_at_is_valid(self):
        """0 is falsy but NOT None"""
        pull = _make_pull(merged_at=0)
        assert is_valid_pull(pull) is True

    def test_d2_false_merged_at_is_valid(self):
        """False is falsy but NOT None"""
        pull = _make_pull(merged_at=False)
        assert is_valid_pull(pull) is True

    def test_d2_empty_list_merged_at_is_valid(self):
        """[] is falsy but NOT None"""
        pull = _make_pull(merged_at=[])
        assert is_valid_pull(pull) is True

    # D3: Type coercion — integer, float, list all valid (not None)
    def test_d3_integer_merged_at(self):
        pull = _make_pull(merged_at=12345)
        assert is_valid_pull(pull) is True

    def test_d3_float_merged_at(self):
        pull = _make_pull(merged_at=1.5)
        assert is_valid_pull(pull) is True

    def test_d3_dict_merged_at(self):
        pull = _make_pull(merged_at={})
        assert is_valid_pull(pull) is True

    # D4: String edge cases
    def test_d4_whitespace_only_merged_at(self):
        pull = _make_pull(merged_at="   \t\n")
        assert is_valid_pull(pull) is True

    def test_d4_unicode_timestamp(self):
        pull = _make_pull(merged_at="\u200b2024-01-01")  # zero-width space prefix
        assert is_valid_pull(pull) is True

    # D5: Date edge cases (all non-None, so all valid)
    def test_d5_epoch_zero_string(self):
        pull = _make_pull(merged_at="1970-01-01T00:00:00Z")
        assert is_valid_pull(pull) is True

    def test_d5_future_date(self):
        pull = _make_pull(merged_at="2099-12-31T23:59:59Z")
        assert is_valid_pull(pull) is True

    # D8: Missing key
    def test_d8_missing_merged_at_key_raises(self):
        pull = {"number": 1, "base": {"sha": "abc"}}
        with pytest.raises(KeyError):
            is_valid_pull(pull)


# ═══════════════════════════════════════════════════════════════════════════════
# is_valid_instance — checks patch is None or patch == ""
# Production: None → False, "" → False, whitespace → True (NOT stripped)
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsValidInstance:
    # D1: Equivalence classes
    def test_d1_valid_patch(self):
        inst = _make_instance(patch_val="diff content")
        assert is_valid_instance(inst) is True

    def test_d1_none_patch_invalid(self):
        inst = _make_instance(patch_val=None)
        assert is_valid_instance(inst) is False

    def test_d1_empty_string_patch_invalid(self):
        inst = _make_instance(patch_val="")
        assert is_valid_instance(inst) is False

    # D2: Whitespace — NOT stripped, so whitespace-only is valid
    def test_d2_whitespace_only_patch_is_valid(self):
        """Production uses == '' not .strip() == '' — whitespace passes"""
        inst = _make_instance(patch_val="   \t\n")
        assert is_valid_instance(inst) is True

    def test_d2_single_space_is_valid(self):
        inst = _make_instance(patch_val=" ")
        assert is_valid_instance(inst) is True

    def test_d2_newline_only_is_valid(self):
        inst = _make_instance(patch_val="\n")
        assert is_valid_instance(inst) is True

    # D3: Type coercion
    def test_d3_integer_patch(self):
        """int is not None and int != '' → valid, but .strip() in has_test_patch would fail"""
        inst = _make_instance(patch_val=42)
        assert is_valid_instance(inst) is True

    def test_d3_list_patch(self):
        inst = _make_instance(patch_val=["diff"])
        assert is_valid_instance(inst) is True

    # D4: String brutality
    def test_d4_unicode_patch(self):
        inst = _make_instance(patch_val="diff \u00e4\u00f6\u00fc")
        assert is_valid_instance(inst) is True

    def test_d4_null_byte_patch(self):
        inst = _make_instance(patch_val="diff\x00content")
        assert is_valid_instance(inst) is True

    def test_d4_very_long_patch(self):
        inst = _make_instance(patch_val="x" * 100_000)
        assert is_valid_instance(inst) is True

    # D1: BVA — single character patch
    def test_d1_bva_single_char_patch(self):
        inst = _make_instance(patch_val="x")
        assert is_valid_instance(inst) is True

    # D8: Missing key
    def test_d8_missing_patch_key_raises(self):
        inst = {"repo": "owner/repo", "test_patch": "diff"}
        with pytest.raises(KeyError):
            is_valid_instance(inst)


# ═══════════════════════════════════════════════════════════════════════════════
# has_test_patch — checks test_patch is None or test_patch.strip() == ""
# Production: None → False, "" → False, whitespace-only → False (stripped)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHasTestPatch:
    # D1: Equivalence classes
    def test_d1_valid_test_patch(self):
        inst = _make_instance(test_patch_val="diff --git a/tests/t.py b/tests/t.py")
        assert has_test_patch(inst) is True

    def test_d1_none_test_patch(self):
        inst = _make_instance(test_patch_val=None)
        assert has_test_patch(inst) is False

    def test_d1_empty_string(self):
        inst = _make_instance(test_patch_val="")
        assert has_test_patch(inst) is False

    # D2: Whitespace — stripped, so whitespace-only is invalid
    def test_d2_whitespace_only_is_false(self):
        """Production uses .strip() == '' — whitespace fails"""
        inst = _make_instance(test_patch_val="   ")
        assert has_test_patch(inst) is False

    def test_d2_tabs_only_is_false(self):
        inst = _make_instance(test_patch_val="\t\t")
        assert has_test_patch(inst) is False

    def test_d2_newlines_only_is_false(self):
        inst = _make_instance(test_patch_val="\n\n\n")
        assert has_test_patch(inst) is False

    def test_d2_mixed_whitespace_is_false(self):
        inst = _make_instance(test_patch_val=" \t\n \r")
        assert has_test_patch(inst) is False

    # D2: Contrast with is_valid_instance — whitespace + non-whitespace
    def test_d2_whitespace_with_content_is_true(self):
        inst = _make_instance(test_patch_val="  diff  ")
        assert has_test_patch(inst) is True

    # D3: Type coercion
    def test_d3_none_patch_is_false(self):
        """None short-circuits before .strip()"""
        inst = _make_instance(test_patch_val=None)
        assert has_test_patch(inst) is False

    def test_d3_integer_raises_attributeerror(self):
        """int has no .strip() method"""
        inst = _make_instance(test_patch_val=42)
        with pytest.raises(AttributeError):
            has_test_patch(inst)

    # D4: String edge cases
    def test_d4_zero_width_space_only(self):
        """\u200b (zero-width space) is NOT whitespace for .strip()"""
        inst = _make_instance(test_patch_val="\u200b")
        assert has_test_patch(inst) is True

    def test_d4_single_char(self):
        inst = _make_instance(test_patch_val="x")
        assert has_test_patch(inst) is True

    # D8: Missing key
    def test_d8_missing_test_patch_key_raises(self):
        inst = {"repo": "owner/repo", "patch": "diff"}
        with pytest.raises(KeyError):
            has_test_patch(inst)

    # D11: Performance — large test patch
    def test_d11_large_test_patch(self):
        inst = _make_instance(test_patch_val="diff " + "x" * 50_000)
        assert has_test_patch(inst) is True


# ═══════════════════════════════════════════════════════════════════════════════
# create_instance — builds instance dict from repo + pull
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateInstance:
    def _setup(self):
        repo = MagicMock()
        repo.repo.full_name = "owner/repo"
        pull = _make_pull(
            number=42,
            base_sha="sha123",
            created_at="2024-06-15T12:00:00Z",
            resolved_issues=["10", "20"],
        )
        return repo, pull

    # D1: Basic construction
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d1_basic_instance_fields(self, mock_patches, mock_hints):
        repo, pull = self._setup()
        mock_patches.return_value = ("fix_patch", "test_patch")
        mock_hints.return_value = ("problem statement", "hints")
        result = create_instance(repo, pull)
        assert result["repo"] == "owner/repo"
        assert result["pull_number"] == 42
        assert result["instance_id"] == "owner__repo-42"
        assert result["issue_numbers"] == ["10", "20"]
        assert result["base_commit"] == "sha123"
        assert result["patch"] == "fix_patch"
        assert result["test_patch"] == "test_patch"
        assert result["problem_statement"] == "problem statement"
        assert result["hints_text"] == "hints"
        assert result["created_at"] == "2024-06-15T12:00:00Z"

    # D1: instance_id format — "/" replaced with "__"
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d1_instance_id_replaces_slash(self, mock_patches, mock_hints):
        repo = MagicMock()
        repo.repo.full_name = "org/nested/repo"
        pull = _make_pull(number=5)
        mock_patches.return_value = ("", "")
        mock_hints.return_value = ("", "")
        result = create_instance(repo, pull)
        assert result["instance_id"] == "org__nested__repo-5"

    # D2: Empty patches and hints
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d2_empty_patches_and_hints(self, mock_patches, mock_hints):
        repo, pull = self._setup()
        mock_patches.return_value = ("", "")
        mock_hints.return_value = ("", "")
        result = create_instance(repo, pull)
        assert result["patch"] == ""
        assert result["test_patch"] == ""
        assert result["problem_statement"] == ""
        assert result["hints_text"] == ""

    # D2: None values from extract functions
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d2_none_values_from_extractors(self, mock_patches, mock_hints):
        repo, pull = self._setup()
        mock_patches.return_value = (None, None)
        mock_hints.return_value = (None, None)
        result = create_instance(repo, pull)
        assert result["patch"] is None
        assert result["test_patch"] is None

    # D4: Unicode in repo name
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d4_unicode_repo_name(self, mock_patches, mock_hints):
        repo = MagicMock()
        repo.repo.full_name = "\u00fc\u00f6\u00e4/r\u00e9po"
        pull = _make_pull(number=1)
        mock_patches.return_value = ("p", "t")
        mock_hints.return_value = ("s", "h")
        result = create_instance(repo, pull)
        assert result["repo"] == "\u00fc\u00f6\u00e4/r\u00e9po"
        assert "__" in result["instance_id"]

    # D1: BVA — pull number 0
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d1_bva_pull_number_zero(self, mock_patches, mock_hints):
        repo, _ = self._setup()
        pull = _make_pull(number=0)
        mock_patches.return_value = ("p", "t")
        mock_hints.return_value = ("s", "h")
        result = create_instance(repo, pull)
        assert result["pull_number"] == 0
        assert result["instance_id"] == "owner__repo-0"

    # D1: BVA — very large pull number
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d1_bva_large_pull_number(self, mock_patches, mock_hints):
        repo, _ = self._setup()
        pull = _make_pull(number=999999999)
        mock_patches.return_value = ("p", "t")
        mock_hints.return_value = ("s", "h")
        result = create_instance(repo, pull)
        assert result["instance_id"] == "owner__repo-999999999"

    # D8: extract_patches raises
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d8_extract_patches_raises_propagates(self, mock_patches, mock_hints):
        repo, pull = self._setup()
        mock_patches.side_effect = RuntimeError("network error")
        with pytest.raises(RuntimeError, match="network error"):
            create_instance(repo, pull)

    # D12: Verify extractors called with correct args
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_d12_extractors_called_correctly(self, mock_patches, mock_hints):
        repo, pull = self._setup()
        mock_patches.return_value = ("p", "t")
        mock_hints.return_value = ("s", "h")
        create_instance(repo, pull)
        mock_patches.assert_called_once_with(pull, repo)
        mock_hints.assert_called_once_with(pull, repo)


# ═══════════════════════════════════════════════════════════════════════════════
# main — orchestrates reading PRs, creating instances, writing output
# ═══════════════════════════════════════════════════════════════════════════════


class TestMain:
    def _write_pr_jsonl(self, path, pulls):
        """Write pull dicts as JSONL"""
        with open(path, "w") as f:
            for pull in pulls:
                f.write(json.dumps(pull) + "\n")

    def _make_full_pull(self, number=1, merged_at="2024-01-01", full_name="owner/repo"):
        return {
            "number": number,
            "merged_at": merged_at,
            "base": {"sha": "abc123", "repo": {"full_name": full_name}},
            "created_at": "2024-01-01",
            "resolved_issues": [],
            "body": "",
            "title": "",
        }

    # D1: Basic pipeline — single valid pull → output
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d1_single_valid_pull(self, MockRepo, mock_patches, mock_hints, tmp_path):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix_patch", "test_patch")
        mock_hints.return_value = ("statement", "hints")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        main(pr_file, output, token="test_token")

        # Check output file
        assert os.path.exists(output)
        with open(output) as f:
            instances = [json.loads(line) for line in f]
        assert len(instances) == 1
        assert instances[0]["repo"] == "owner/repo"
        assert instances[0]["patch"] == "fix_patch"

    # D1: Skip unmerged pulls
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d1_skips_unmerged_pulls(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(
            pr_file,
            [
                self._make_full_pull(number=1, merged_at=None),
                self._make_full_pull(number=2, merged_at="2024-01-01"),
            ],
        )
        main(pr_file, output, token="tok")

        with open(output) as f:
            instances = [json.loads(line) for line in f]
        assert len(instances) == 1
        assert instances[0]["pull_number"] == 2

    # D1: Empty patch → not written to output, but written to .all
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d1_empty_patch_excluded_from_output(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("", "test_patch")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        main(pr_file, output, token="tok")

        # Output should not exist or be empty (no valid instances)
        if os.path.exists(output):
            with open(output) as f:
                assert f.read().strip() == ""

    # D1: No test patch → written to .all but not to output
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d1_no_test_patch_excluded_from_output(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix_patch", "")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        main(pr_file, output, token="tok")

        # .all should have the instance
        all_output = output + ".all"
        assert os.path.exists(all_output)
        with open(all_output) as f:
            all_instances = [json.loads(line) for line in f]
        assert len(all_instances) == 1

        # output should be empty (no test patch)
        if os.path.exists(output):
            with open(output) as f:
                assert f.read().strip() == ""

    # D6: Resume from existing .all file — skip seen PRs
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d6_resumes_from_existing_all_file(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        all_output = output + ".all"

        # Pre-populate .all with PR #1
        with open(all_output, "w") as f:
            f.write(
                json.dumps(
                    {
                        "repo": "owner/repo",
                        "pull_number": 1,
                        "instance_id": "owner__repo-1",
                        "patch": "fix",
                        "test_patch": "test",
                    }
                )
                + "\n"
            )

        # Input has PR #1 and #2
        self._write_pr_jsonl(
            pr_file,
            [
                self._make_full_pull(number=1),
                self._make_full_pull(number=2),
            ],
        )
        main(pr_file, output, token="tok")

        # Only PR #2 should be processed (PR #1 skipped as seen)
        # extract_patches should only be called once (for PR #2)
        assert mock_patches.call_count == 1

    # D2: Token from environment
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d2_token_from_env(
        self, MockRepo, mock_patches, mock_hints, tmp_path, monkeypatch
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")
        monkeypatch.setenv("GITHUB_TOKEN", "env_token")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        main(pr_file, output, token=None)

        MockRepo.assert_called_once_with("owner", "repo", token="env_token")

    # D2: No token at all
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d2_no_token_uses_none(
        self, MockRepo, mock_patches, mock_hints, tmp_path, monkeypatch
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        main(pr_file, output, token=None)

        MockRepo.assert_called_once_with("owner", "repo", token=None)

    # D1: Multiple pulls from different repos
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d1_multiple_repos(self, MockRepo, mock_patches, mock_hints, tmp_path):
        repo_a = MagicMock()
        repo_a.repo.full_name = "org/repoA"
        repo_b = MagicMock()
        repo_b.repo.full_name = "org/repoB"
        MockRepo.side_effect = [repo_a, repo_b]
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(
            pr_file,
            [
                self._make_full_pull(number=1, full_name="org/repoA"),
                self._make_full_pull(number=2, full_name="org/repoB"),
            ],
        )
        main(pr_file, output, token="tok")

        with open(output) as f:
            instances = [json.loads(line) for line in f]
        assert len(instances) == 2
        repos_seen = {i["repo"] for i in instances}
        assert repos_seen == {"org/repoA", "org/repoB"}

    # D6: Repo caching — same repo not constructed twice
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d6_repo_cached_not_duplicated(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(
            pr_file,
            [
                self._make_full_pull(number=1),
                self._make_full_pull(number=2),
            ],
        )
        main(pr_file, output, token="tok")

        # Repo constructed only once despite 2 pulls from same repo
        assert MockRepo.call_count == 1

    # D8: Empty PR file → no output
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d8_empty_pr_file(self, MockRepo, tmp_path):
        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        with open(pr_file, "w") as f:
            pass  # empty file
        main(pr_file, output, token="tok")
        MockRepo.assert_not_called()

    # D10: Malformed JSON in PR file
    def test_d10_malformed_json_raises(self, tmp_path):
        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        with open(pr_file, "w") as f:
            f.write("not valid json\n")
        with pytest.raises(json.JSONDecodeError):
            main(pr_file, output, token="tok")

    # D10: Mixed valid/invalid JSON in .all file
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d10_malformed_json_in_all_file_raises(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        all_output = output + ".all"
        with open(all_output, "w") as f:
            f.write("broken json\n")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        with pytest.raises(json.JSONDecodeError):
            main(pr_file, output, token="tok")

    # D9: Token not leaked in output
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d9_token_not_in_output(self, MockRepo, mock_patches, mock_hints, tmp_path):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        self._write_pr_jsonl(pr_file, [self._make_full_pull()])
        secret_token = "ghp_SuperSecret123"
        main(pr_file, output, token=secret_token)

        with open(output) as f:
            content = f.read()
        assert secret_token not in content
        all_output = output + ".all"
        with open(all_output) as f:
            all_content = f.read()
        assert secret_token not in all_content

    # D11: Multiple pulls processing
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d11_fifty_pulls(self, MockRepo, mock_patches, mock_hints, tmp_path):
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        pulls = [self._make_full_pull(number=i) for i in range(50)]
        self._write_pr_jsonl(pr_file, pulls)
        main(pr_file, output, token="tok")

        with open(output) as f:
            instances = [json.loads(line) for line in f]
        assert len(instances) == 50

    # D6: .all file instance_id reconstruction (missing instance_id in .all)
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    @patch("swefficiency.collect.build_dataset.Repo")
    def test_d6_all_file_missing_instance_id_reconstructed(
        self, MockRepo, mock_patches, mock_hints, tmp_path
    ):
        """Production reconstructs instance_id if missing from .all entries"""
        mock_repo = MagicMock()
        mock_repo.repo.full_name = "owner/repo"
        MockRepo.return_value = mock_repo
        mock_patches.return_value = ("fix", "test")
        mock_hints.return_value = ("s", "h")

        pr_file = str(tmp_path / "prs.jsonl")
        output = str(tmp_path / "output.jsonl")
        all_output = output + ".all"

        # .all entry WITHOUT instance_id
        with open(all_output, "w") as f:
            f.write(
                json.dumps(
                    {
                        "repo": "owner/repo",
                        "pull_number": 1,
                        "patch": "fix",
                        "test_patch": "test",
                    }
                )
                + "\n"
            )

        self._write_pr_jsonl(pr_file, [self._make_full_pull(number=1)])
        main(pr_file, output, token="tok")

        # PR #1 should be skipped (reconstructed instance_id matches)
        assert mock_patches.call_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: is_valid_pull → create_instance → is_valid_instance → has_test_patch
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildDatasetIntegration:
    # D12: Full pipeline through validators
    def test_d12_valid_pull_valid_instance_with_test(self):
        pull = _make_pull(merged_at="2024-01-01")
        assert is_valid_pull(pull) is True
        inst = _make_instance(patch_val="fix", test_patch_val="test")
        assert is_valid_instance(inst) is True
        assert has_test_patch(inst) is True

    def test_d12_valid_pull_valid_instance_no_test(self):
        pull = _make_pull(merged_at="2024-01-01")
        assert is_valid_pull(pull) is True
        inst = _make_instance(patch_val="fix", test_patch_val="")
        assert is_valid_instance(inst) is True
        assert has_test_patch(inst) is False

    def test_d12_valid_pull_invalid_instance(self):
        pull = _make_pull(merged_at="2024-01-01")
        assert is_valid_pull(pull) is True
        inst = _make_instance(patch_val="", test_patch_val="test")
        assert is_valid_instance(inst) is False

    def test_d12_invalid_pull_never_reaches_instance(self):
        pull = _make_pull(merged_at=None)
        assert is_valid_pull(pull) is False
        # In production, create_instance is never called for invalid pulls

    # D12: Whitespace asymmetry between is_valid_instance and has_test_patch
    def test_d12_whitespace_asymmetry(self):
        """patch='  ' → valid instance (no strip), test_patch='  ' → no test (stripped)"""
        inst = _make_instance(patch_val="  ", test_patch_val="  ")
        assert is_valid_instance(inst) is True
        assert has_test_patch(inst) is False



# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: is_valid_pull  (D1/D2/D3/D4/D5)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsValidPullExpanded:
    """D1/D2/D3/D4/D5: Exhaustive merged_at testing."""

    @pytest.mark.parametrize("year", list(range(1970, 2100)))
    def test_year_range_valid(self, year):
        """D1/BVA: Every year from 1970-2099 is valid."""
        assert is_valid_pull({"merged_at": f"{year}-01-01"}) is True

    @pytest.mark.parametrize(
        "merged_at",
        [
            # D2: Falsy-but-not-None
            "", "0", 0, False, 0.0, [], {}, set(), tuple(),
            b"", frozenset(), complex(0, 0),
            # D3: Various non-None types
            42, 3.14, True, [1, 2], {"a": 1}, (1,), b"bytes",
            -1, -0.0, float("inf"), float("-inf"),
            float("nan"), 1e100, -1e100,
            # D4: Various strings
            " ", "\t", "\n", "\r\n", "\x00",
            "null", "None", "undefined", "NaN",
            "true", "false", "yes", "no",
            "hello", "2023", "not-a-date",
            "1970-01-01T00:00:00Z",
            "2099-12-31T23:59:59.999999Z",
        ],
    )
    def test_non_none_valid(self, merged_at):
        """D2/D3: Anything that is not None is valid."""
        assert is_valid_pull({"merged_at": merged_at}) is True

    @pytest.mark.parametrize(
        "merged_at",
        [None],
    )
    def test_none_invalid(self, merged_at):
        """D2: Only None is invalid."""
        assert is_valid_pull({"merged_at": merged_at}) is False

    @pytest.mark.parametrize("i", list(range(100)))
    def test_integer_values_valid(self, i):
        """D3: Integer values 0-99 are all valid (not None)."""
        assert is_valid_pull({"merged_at": i}) is True

    @pytest.mark.parametrize("i", list(range(-50, 0)))
    def test_negative_integers_valid(self, i):
        """D3: Negative integers are all valid (not None)."""
        assert is_valid_pull({"merged_at": i}) is True

    @pytest.mark.parametrize("char", [chr(i) for i in range(32, 127)])
    def test_single_ascii_char_valid(self, char):
        """D4: Every printable ASCII character is valid as merged_at."""
        assert is_valid_pull({"merged_at": char}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: is_valid_instance  (D1/D2/D3/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsValidInstanceExpanded:
    """D1/D2/D3/D4: Exhaustive patch testing."""

    @pytest.mark.parametrize("char", [chr(i) for i in range(32, 127)])
    def test_single_ascii_char_valid(self, char):
        """D4: Every printable ASCII character as patch is valid."""
        assert is_valid_instance({"patch": char}) is True

    @pytest.mark.parametrize("length", list(range(1, 201)))
    def test_string_lengths_1_to_200(self, length):
        """D1/BVA: String lengths 1-200 are all valid."""
        assert is_valid_instance({"patch": "x" * length}) is True

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_spaces_valid_no_strip(self, n):
        """D4: 1-100 spaces are valid (no strip in is_valid_instance)."""
        assert is_valid_instance({"patch": " " * n}) is True

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_newlines_valid_no_strip(self, n):
        """D4: 1-100 newlines are valid (no strip)."""
        assert is_valid_instance({"patch": "\n" * n}) is True

    @pytest.mark.parametrize(
        "patch",
        [
            # D10: Various encodings/formats
            "\xc3\xa9",  # UTF-8 bytes as string
            "caf\u00e9",  # accented
            "\u4e2d\u6587",  # Chinese
            "\ud55c\uad6d\uc5b4",  # Korean
            "\u65e5\u672c\u8a9e",  # Japanese
            "\U0001f600",  # emoji
            "\u2603",  # snowman
            "\u2764",  # heart
            "\u00a9",  # copyright
            "\u00ae",  # registered
            "\u2122",  # trademark
            "\u00b0",  # degree
            "\u00b1",  # plus-minus
            "\u00d7",  # multiplication
            "\u00f7",  # division
            "\u221a",  # square root
            "\u03c0",  # pi
            "\u03b1",  # alpha
            "\u03b2",  # beta
            "\u03b3",  # gamma
        ],
    )
    def test_unicode_patches_valid(self, patch):
        """D4/D10: Various unicode strings are valid patches."""
        assert is_valid_instance({"patch": patch}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: has_test_patch  (D1/D2/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveHasTestPatchExpanded:
    """D1/D2/D4: Exhaustive test_patch testing."""

    @pytest.mark.parametrize("char", [chr(i) for i in range(33, 127)])
    def test_single_non_whitespace_ascii_valid(self, char):
        """D4: Every printable non-whitespace ASCII as test_patch is valid."""
        assert has_test_patch({"test_patch": char}) is True

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_spaces_invalid_strip(self, n):
        """D4: 1-100 spaces are invalid (strip applied)."""
        assert has_test_patch({"test_patch": " " * n}) is False

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_tabs_invalid_strip(self, n):
        """D4: 1-100 tabs are invalid (strip applied)."""
        assert has_test_patch({"test_patch": "\t" * n}) is False

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_newlines_invalid_strip(self, n):
        """D4: 1-100 newlines are invalid (strip applied)."""
        assert has_test_patch({"test_patch": "\n" * n}) is False

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_char_padded_spaces_valid(self, n):
        """D4: 'x' padded with n spaces is valid after strip."""
        assert has_test_patch({"test_patch": " " * n + "x" + " " * n}) is True

    @pytest.mark.parametrize("length", list(range(1, 201)))
    def test_content_lengths_valid(self, length):
        """D1/BVA: Content of length 1-200 is valid."""
        assert has_test_patch({"test_patch": "a" * length}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE 2: Additional parametrized expansion
# ═══════════════════════════════════════════════════════════════════════════════


class TestWave2IsValidPullFalsyValues:
    """D2/D3: Exhaustive falsy-but-not-None values are all valid."""

    FALSY_NOT_NONE = [
        0, 0.0, False, "", [], {}, set(), tuple(), frozenset(),
        b"", bytearray(), complex(0, 0), range(0),
    ]

    @pytest.mark.parametrize("val", FALSY_NOT_NONE)
    def test_falsy_but_not_none_valid(self, val):
        """D2: Only None is invalid, all other falsy values are valid merged_at."""
        assert is_valid_pull({"merged_at": val}) is True


class TestWave2IsValidPullStringVariants:
    """D4: Various string formats in merged_at."""

    @pytest.mark.parametrize(
        "val",
        [
            "2024", "2024-01", "2024-01-01",
            "Jan 1 2024", "1/1/2024", "01-01-2024",
            "2024/01/01", "20240101", "2024.01.01",
            "yesterday", "now", "today", "tomorrow",
            "1 hour ago", "last week", "next month",
            "T00:00:00Z", "Z", "UTC", "GMT",
            " ", "\t", "\n", "\r\n", "\x00",
            "null", "None", "undefined", "NaN",
            "true", "false", "TRUE", "FALSE",
            "0", "1", "-1", "999999999",
        ],
    )
    def test_string_variants_valid(self, val):
        """D4: Any non-None string is a valid merged_at."""
        assert is_valid_pull({"merged_at": val}) is True


class TestWave2IsValidInstanceUnicodePatches:
    """D4: Unicode content as patches."""

    UNICODE_PATCHES = [
        "修复性能问题", "パフォーマンスの改善", "성능 향상",
        "تحسين الأداء", "Улучшение производительности",
        "Βελτίωση απόδοσης", "प्रदर्शन सुधार",
        "🚀 faster", "⚡ optimized", "🔥 hot path",
        "café résumé naïve", "Ñoño señor",
        "ÄÖÜäöüß", "ÆØÅæøå", "ĐđĆćŠšŽž",
        "\u200b\u200c\u200d\ufeff",
        "a\u0300 e\u0301 i\u0302 o\u0303 u\u0308",
        "H\u0065\u0301llo",
        "\U0001f600\U0001f4a9\U0001f525",
        "a" * 10000,
        "\n" * 100 + "patch content" + "\n" * 100,
        "---\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new",
    ]

    @pytest.mark.parametrize("patch", UNICODE_PATCHES)
    def test_unicode_patches_valid(self, patch):
        """D4: Unicode patches are all valid."""
        inst = {"patch": patch, "test_patch": None}
        assert is_valid_instance(inst) is True


class TestWave2HasTestPatchContentVariants:
    """D4: Various non-whitespace content is valid."""

    VALID_PATCHES = [
        "x", "ab", "abc", "test", ".",  "-", "+", "=",
        "0", "1", "00", "01", "10", "99",
        "diff --git", "@@", "---", "+++",
        "import pytest", "def test_foo():", "assert True",
        "class TestFoo:", "    pass", "# comment",
        "\t\tcontent", "  content  ",
        "\n\ncontent\n\n",
        "a\tb\tc",
        "line1\nline2\nline3",
    ]

    @pytest.mark.parametrize("patch", VALID_PATCHES)
    def test_content_patches_valid(self, patch):
        """D4: Various non-whitespace content is valid."""
        inst = {"test_patch": patch, "patch": "x"}
        assert has_test_patch(inst) is True


class TestWave2CreateInstanceFieldCombinations:
    """D12: Various field combination interactions."""

    @pytest.mark.parametrize("num_issues", list(range(0, 11)))
    @patch("swefficiency.collect.build_dataset.extract_problem_statement_and_hints")
    @patch("swefficiency.collect.build_dataset.extract_patches")
    def test_varying_issue_counts(self, mock_ep, mock_ps, num_issues):
        """D1/BVA: 0-10 resolved issues."""
        mock_ep.return_value = ("patch", "test_patch")
        mock_ps.return_value = ("problem", "hints")
        issues = [str(i) for i in range(num_issues)]
        pull = _make_pull(resolved_issues=issues)
        from swefficiency.collect.build_dataset import create_instance
        inst = create_instance(MagicMock(full_name="o/r"), pull)
        assert inst["issue_numbers"] == issues
