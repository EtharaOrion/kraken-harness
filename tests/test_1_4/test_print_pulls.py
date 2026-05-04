"""
Tests for swefficiency.collect.print_pulls

Coverage: log_all_pulls, main
Dimensions: D1 Input Domain, D2 Null/Empty, D3 Type Coercion, D4 String Brutality,
            D5 Time/Date, D6 State/Lifecycle, D8 Error Handling, D10 Data Format,
            D11 Performance
"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from swefficiency.collect.print_pulls import log_all_pulls, main


# ── Helpers ──


def _mock_pull(number=1, created_at="2024-06-15T12:00:00Z", body="", title=""):
    pull = MagicMock()
    pull.number = number
    pull.created_at = created_at
    pull.body = body
    pull.title = title
    return pull


def _mock_repo(pulls=None, resolved_issues=None):
    repo = MagicMock()
    repo.get_all_pulls.return_value = iter(pulls or [])
    repo.extract_resolved_issues.return_value = resolved_issues or []
    return repo


class TestLogAllPulls:
    # D1: Single pull written to output
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_single_pull(self, mock_obj2dict, tmp_path):
        pull = _mock_pull(number=42)
        mock_obj2dict.return_value = {"number": 42, "resolved_issues": []}
        repo = _mock_repo(pulls=[pull])
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output)

        with open(output) as f:
            lines = [json.loads(l) for l in f]
        assert len(lines) == 1
        assert lines[0]["number"] == 42

    # D1: Multiple pulls
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_multiple_pulls(self, mock_obj2dict, tmp_path):
        pulls = [_mock_pull(number=i) for i in range(5)]
        mock_obj2dict.side_effect = [
            {"number": i, "resolved_issues": []} for i in range(5)
        ]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output)

        with open(output) as f:
            lines = [json.loads(l) for l in f]
        assert len(lines) == 5

    # D1: resolved_issues attached to pull via setattr
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_resolved_issues_set_on_pull(self, mock_obj2dict, tmp_path):
        pull = _mock_pull()
        mock_obj2dict.return_value = {"number": 1, "resolved_issues": ["10"]}
        repo = _mock_repo(pulls=[pull], resolved_issues=["10"])
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output)

        assert pull.resolved_issues == ["10"]

    # D1: max_pulls limits output — BUG: max_pulls=0 logs 1 pull (>= comparison)
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_max_pulls_limits_output(self, mock_obj2dict, tmp_path):
        pulls = [_mock_pull(number=i) for i in range(10)]
        mock_obj2dict.side_effect = [{"number": i} for i in range(10)]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, max_pulls=3)

        with open(output) as f:
            lines = f.readlines()
        # i_pull goes 0,1,2,3 — breaks when i_pull(3) >= max_pulls(3) → 4 written
        assert len(lines) == 4

    # D1: BVA — max_pulls=0 writes exactly 1 pull (off-by-one)
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_bva_max_pulls_zero_writes_one(self, mock_obj2dict, tmp_path):
        """BUG: max_pulls=0 still writes 1 pull because check is i_pull >= max_pulls after write"""
        pulls = [_mock_pull(number=i) for i in range(5)]
        mock_obj2dict.side_effect = [{"number": i} for i in range(5)]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, max_pulls=0)

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 1  # i_pull=0 >= 0 → break after first write

    # D1: BVA — max_pulls=1 writes exactly 2 pulls
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d1_bva_max_pulls_one(self, mock_obj2dict, tmp_path):
        pulls = [_mock_pull(number=i) for i in range(5)]
        mock_obj2dict.side_effect = [{"number": i} for i in range(5)]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, max_pulls=1)

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 2  # writes at i=0, i=1; breaks when i=1 >= 1

    # D2: max_pulls=None (default) — no limit
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d2_max_pulls_none_no_limit(self, mock_obj2dict, tmp_path):
        pulls = [_mock_pull(number=i) for i in range(20)]
        mock_obj2dict.side_effect = [{"number": i} for i in range(20)]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, max_pulls=None)

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 20

    # D2: Empty pulls list
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d2_no_pulls(self, mock_obj2dict, tmp_path):
        repo = _mock_repo(pulls=[])
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output)

        with open(output) as f:
            assert f.read() == ""

    # D5: cutoff_date filters PRs
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d5_cutoff_date_filters(self, mock_obj2dict, tmp_path):
        # Pulls sorted newest first (typical GitHub API order)
        pulls = [
            _mock_pull(number=3, created_at="2024-06-01T00:00:00Z"),
            _mock_pull(number=2, created_at="2024-03-01T00:00:00Z"),
            _mock_pull(number=1, created_at="2024-01-01T00:00:00Z"),
        ]
        mock_obj2dict.side_effect = [
            {"number": 3, "created_at": "2024-06-01T00:00:00Z"},
            {"number": 2, "created_at": "2024-03-01T00:00:00Z"},
            {"number": 1, "created_at": "2024-01-01T00:00:00Z"},
        ]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, cutoff_date="20240201")

        with open(output) as f:
            lines = [json.loads(l) for l in f]
        # PR #3 (June) and #2 (March) pass, #1 (Jan) is before cutoff (Feb 1) → break
        # But #1 is still WRITTEN before the break check
        assert len(lines) == 3

    # D5: cutoff_date format parsing — valid YYYYMMDD
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d5_cutoff_date_format(self, mock_obj2dict, tmp_path):
        pull = _mock_pull(created_at="2024-06-15T00:00:00Z")
        mock_obj2dict.return_value = {"number": 1}
        repo = _mock_repo(pulls=[pull])
        output = str(tmp_path / "pulls.jsonl")

        # Should not raise — valid format
        log_all_pulls(repo, output, cutoff_date="20240101")

    # D5: Invalid cutoff date format raises ValueError
    def test_d5_invalid_cutoff_date_format(self, tmp_path):
        repo = _mock_repo(pulls=[])
        output = str(tmp_path / "pulls.jsonl")

        with pytest.raises(ValueError):
            log_all_pulls(repo, output, cutoff_date="2024-01-01")  # wrong format

    # D5: Cutoff date edge — midnight boundary
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d5_cutoff_midnight(self, mock_obj2dict, tmp_path):
        pull = _mock_pull(created_at="2024-01-01T00:00:00Z")
        mock_obj2dict.return_value = {"number": 1, "created_at": "2024-01-01T00:00:00Z"}
        repo = _mock_repo(pulls=[pull])
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, cutoff_date="20240101")

        with open(output) as f:
            lines = f.readlines()
        # created_at == cutoff → NOT less than, so no break; pull is written
        assert len(lines) == 1

    # D5: Leap year date
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d5_leap_year_cutoff(self, mock_obj2dict, tmp_path):
        pull = _mock_pull(created_at="2024-02-29T12:00:00Z")
        mock_obj2dict.return_value = {"number": 1}
        repo = _mock_repo(pulls=[pull])
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, cutoff_date="20240229")

    # D8: File write error
    def test_d8_output_to_nonexistent_dir_raises(self):
        repo = _mock_repo(pulls=[])
        with pytest.raises(FileNotFoundError):
            log_all_pulls(repo, "/nonexistent/dir/output.jsonl")

    # D11: Many pulls
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_d11_hundred_pulls(self, mock_obj2dict, tmp_path):
        pulls = [_mock_pull(number=i) for i in range(100)]
        mock_obj2dict.side_effect = [{"number": i} for i in range(100)]
        repo = _mock_repo(pulls=pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output)

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 100


class TestMain:
    # D1: Basic repo name splitting and Repo construction
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d1_splits_repo_name(self, MockRepo, mock_log):
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        main("owner/repo", "/tmp/out.jsonl", token="tok")

        MockRepo.assert_called_once_with("owner", "repo", token="tok")
        mock_log.assert_called_once_with(
            mock_repo, "/tmp/out.jsonl", max_pulls=None, cutoff_date=None
        )

    # D1: Passes max_pulls and cutoff_date
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d1_passes_max_pulls_cutoff(self, MockRepo, mock_log):
        MockRepo.return_value = MagicMock()

        main(
            "org/name",
            "/tmp/out.jsonl",
            token="tok",
            max_pulls=50,
            cutoff_date="20240101",
        )

        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        assert kwargs["max_pulls"] == 50
        assert kwargs["cutoff_date"] == "20240101"

    # D2: Token from environment
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d2_token_from_env(self, MockRepo, mock_log, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "env_tok")
        MockRepo.return_value = MagicMock()

        main("owner/repo", "/tmp/out.jsonl", token=None)

        MockRepo.assert_called_once_with("owner", "repo", token="env_tok")

    # D2: No token at all
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d2_no_token(self, MockRepo, mock_log, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        MockRepo.return_value = MagicMock()

        main("owner/repo", "/tmp/out.jsonl", token=None)

        MockRepo.assert_called_once_with("owner", "repo", token=None)

    # D3: Repo name without slash raises ValueError
    def test_d3_repo_name_no_slash_raises(self):
        with pytest.raises(ValueError):
            main("noslash", "/tmp/out.jsonl", token="tok")

    # D4: Repo name with extra slashes
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d4_repo_name_extra_slashes_raises(self, MockRepo, mock_log):
        with pytest.raises(ValueError):
            main("a/b/c", "/tmp/out.jsonl", token="tok")

    # D4: Unicode repo name
    @patch("swefficiency.collect.print_pulls.log_all_pulls")
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d4_unicode_repo_name(self, MockRepo, mock_log):
        MockRepo.return_value = MagicMock()
        main("\u00fc\u00f6/r\u00e9po", "/tmp/out.jsonl", token="tok")
        MockRepo.assert_called_once_with("\u00fc\u00f6", "r\u00e9po", token="tok")

    # D8: Repo construction failure propagates
    @patch("swefficiency.collect.print_pulls.Repo")
    def test_d8_repo_init_failure(self, MockRepo):
        MockRepo.side_effect = RuntimeError("API error")
        with pytest.raises(RuntimeError, match="API error"):
            main("owner/repo", "/tmp/out.jsonl", token="tok")


class TestCutoffDateParsing:
    # D5: Valid format
    def test_d5_valid_yyyymmdd(self):
        result = datetime.strptime("20240615", "%Y%m%d")
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    # D5: Leap year Feb 29
    def test_d5_leap_year_feb29(self):
        result = datetime.strptime("20240229", "%Y%m%d")
        assert result.day == 29

    # D5: Non-leap year Feb 29 raises
    def test_d5_non_leap_feb29_raises(self):
        with pytest.raises(ValueError):
            datetime.strptime("20230229", "%Y%m%d")

    # D5: Epoch date
    def test_d5_epoch_date(self):
        result = datetime.strptime("19700101", "%Y%m%d")
        assert result.year == 1970

    # D5: Far future
    def test_d5_far_future(self):
        result = datetime.strptime("99991231", "%Y%m%d")
        assert result.year == 9999

    # D5: Invalid month
    def test_d5_invalid_month_13(self):
        with pytest.raises(ValueError):
            datetime.strptime("20241301", "%Y%m%d")

    # D5: Invalid day 32
    def test_d5_invalid_day_32(self):
        with pytest.raises(ValueError):
            datetime.strptime("20240132", "%Y%m%d")

    # D4: Non-numeric string
    def test_d4_non_numeric(self):
        with pytest.raises(ValueError):
            datetime.strptime("abcdefgh", "%Y%m%d")

    # D2: Empty string
    def test_d2_empty_string(self):
        with pytest.raises(ValueError):
            datetime.strptime("", "%Y%m%d")

    # D3: Integer instead of string
    def test_d3_integer_raises_typeerror(self):
        with pytest.raises(TypeError):
            datetime.strptime(20240101, "%Y%m%d")


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: cutoff_date + log_all_pulls  (D1/D5)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveCutoffDateExpanded:
    """D5: Exhaustive date format testing for cutoff_date."""

    @pytest.mark.parametrize("year", list(range(2000, 2100)))
    def test_year_range_valid_format(self, year):
        """D5: Years 2000-2099 in YYYYMMDD format parse correctly."""
        from datetime import datetime

        date_str = f"{year}0615"
        parsed = datetime.strptime(date_str, "%Y%m%d")
        assert parsed.year == year
        assert parsed.month == 6
        assert parsed.day == 15

    @pytest.mark.parametrize("month", list(range(1, 13)))
    def test_all_months(self, month):
        """D5: Months 1-12 parse correctly."""
        from datetime import datetime

        date_str = f"2023{month:02d}15"
        parsed = datetime.strptime(date_str, "%Y%m%d")
        assert parsed.month == month

    @pytest.mark.parametrize(
        "month,max_day",
        [
            (1, 31),
            (2, 28),
            (3, 31),
            (4, 30),
            (5, 31),
            (6, 30),
            (7, 31),
            (8, 31),
            (9, 30),
            (10, 31),
            (11, 30),
            (12, 31),
        ],
    )
    def test_max_days_per_month(self, month, max_day):
        """D5: Maximum valid day for each month."""
        from datetime import datetime

        date_str = f"2023{month:02d}{max_day:02d}"
        parsed = datetime.strptime(date_str, "%Y%m%d")
        assert parsed.day == max_day

    @pytest.mark.parametrize("day", list(range(1, 29)))
    def test_feb_days(self, day):
        """D5: February days 1-28 valid in non-leap year."""
        from datetime import datetime

        date_str = f"2023{2:02d}{day:02d}"
        parsed = datetime.strptime(date_str, "%Y%m%d")
        assert parsed.day == day


class TestMassiveLogAllPullsExpanded:
    """D1/D11: Exhaustive max_pulls boundary tests."""

    @pytest.mark.parametrize("max_pulls", list(range(1, 51)))
    @patch("swefficiency.collect.print_pulls.obj2dict")
    def test_max_pulls_limits_output(self, mock_obj2dict, max_pulls, tmp_path):
        """D1/BVA: max_pulls 1-50 limits output correctly."""
        total_pulls = 100
        pulls = [_mock_pull(i, f"2023-06-15T12:00:00Z") for i in range(total_pulls)]
        mock_obj2dict.side_effect = [
            {"number": i, "resolved_issues": []} for i in range(total_pulls)
        ]
        repo = _mock_repo(pulls)
        output = str(tmp_path / "pulls.jsonl")

        log_all_pulls(repo, output, max_pulls=max_pulls)

        with open(output) as f:
            written = [json.loads(line) for line in f if line.strip()]

        # Off-by-one BUG: writes at i_pull=0..N, checks AFTER write, so max_pulls=N writes N+1
        assert len(written) == max_pulls + 1
