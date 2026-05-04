"""
Tests for swefficiency.collect.get_tasks_pipeline

Coverage: split_instances, construct_data_files, main
Dimensions: D1 Input Domain, D2 Null/Empty, D3 Type Coercion, D4 String Brutality,
            D6 State/Lifecycle, D7 Concurrency, D8 Error Handling, D11 Performance
"""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from swefficiency.collect.get_tasks_pipeline import (
    split_instances,
    construct_data_files,
    main,
)


class TestSplitInstances:
    # D1: Even split
    def test_d1_even_split(self):
        result = split_instances([1, 2, 3, 4], 2)
        assert result == [[1, 2], [3, 4]]

    # D1: Uneven split — remainder distributed to first sublists
    def test_d1_uneven_split(self):
        result = split_instances([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2, 3], [4, 5]]

    def test_d1_uneven_split_3(self):
        result = split_instances([1, 2, 3, 4, 5], 3)
        assert result == [[1, 2], [3, 4], [5]]

    # D1: n == len(list) → each sublist has 1 element
    def test_d1_n_equals_length(self):
        result = split_instances([1, 2, 3], 3)
        assert result == [[1], [2], [3]]

    # D1: n > len(list) → some sublists empty
    def test_d1_n_greater_than_length(self):
        result = split_instances([1, 2], 5)
        assert len(result) == 5
        non_empty = [s for s in result if s]
        assert len(non_empty) == 2

    # D1: n == 1 → entire list in one sublist
    def test_d1_n_equals_one(self):
        result = split_instances([1, 2, 3, 4], 1)
        assert result == [[1, 2, 3, 4]]

    # D2: Empty list
    def test_d2_empty_list(self):
        result = split_instances([], 3)
        assert result == [[], [], []]

    # D2: Single element
    def test_d2_single_element(self):
        result = split_instances([42], 1)
        assert result == [[42]]

    # D8: n=0 raises ZeroDivisionError (BUG in production)
    def test_d8_n_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            split_instances([1, 2, 3], 0)

    # D3: Negative n — creates empty result (range(-1) = empty)
    def test_d3_negative_n(self):
        result = split_instances([1, 2], -1)
        assert result == []

    # D1: All elements preserved
    def test_d1_all_elements_preserved(self):
        original = list(range(100))
        result = split_instances(original, 7)
        flat = [item for sublist in result for item in sublist]
        assert flat == original

    # D1: Order preserved
    def test_d1_order_preserved(self):
        original = list(range(50))
        result = split_instances(original, 4)
        flat = [item for sublist in result for item in sublist]
        assert flat == original

    # D1: Correct number of sublists
    def test_d1_correct_sublist_count(self):
        for n in [1, 2, 3, 5, 10]:
            result = split_instances(list(range(20)), n)
            assert len(result) == n

    # D3: Non-list iterable (tuple)
    def test_d3_tuple_input(self):
        result = split_instances((1, 2, 3), 2)
        assert len(result) == 2

    # D4: String elements (not split into chars)
    def test_d4_string_elements(self):
        result = split_instances(["repo/a", "repo/b", "repo/c"], 2)
        flat = [item for sublist in result for item in sublist]
        assert flat == ["repo/a", "repo/b", "repo/c"]

    # D11: Large list
    def test_d11_large_list(self):
        result = split_instances(list(range(10_000)), 100)
        assert len(result) == 100
        flat = [item for sublist in result for item in sublist]
        assert len(flat) == 10_000

    # D1: BVA — n == len(list) + 1
    def test_d1_bva_n_one_more_than_length(self):
        result = split_instances([1, 2, 3], 4)
        assert len(result) == 4
        assert sum(len(s) for s in result) == 3

    # D1: Sublist sizes differ by at most 1
    def test_d1_sublist_size_invariant(self):
        for n in range(1, 20):
            result = split_instances(list(range(37)), n)
            sizes = [len(s) for s in result]
            assert max(sizes) - min(sizes) <= 1


class TestConstructDataFiles:
    def _make_data(
        self,
        repos=None,
        path_prs="/tmp/prs",
        path_tasks="/tmp/tasks",
        max_pulls=None,
        cutoff_date=None,
        token="tok",
    ):
        return {
            "repos": repos if repos is not None else ["owner/repo"],
            "path_prs": path_prs,
            "path_tasks": path_tasks,
            "max_pulls": max_pulls,
            "cutoff_date": cutoff_date,
            "token": token,
        }

    # D1: Creates PR and task files for single repo
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d1_creates_files_single_repo(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(repos=["org/myrepo"])
        construct_data_files(data)
        mock_pp.assert_called_once()
        mock_bd.assert_called_once()

    # D6: Skips existing PR file
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d6_skips_existing_pr_file(self, mock_exists, mock_pp, mock_bd):
        # PR exists, task does not
        mock_exists.side_effect = lambda p: "prs" in p
        data = self._make_data()
        construct_data_files(data)
        mock_pp.assert_not_called()
        mock_bd.assert_called_once()

    # D6: Skips existing task file
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d6_skips_existing_task_file(self, mock_exists, mock_pp, mock_bd):
        # Both exist
        mock_exists.return_value = True
        data = self._make_data()
        construct_data_files(data)
        mock_pp.assert_not_called()
        mock_bd.assert_not_called()

    # D5: cutoff_date in filename
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d5_cutoff_date_in_filename(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(repos=["org/myrepo"], cutoff_date="20240101")
        construct_data_files(data)
        call_args = mock_pp.call_args
        pr_path = call_args[0][1]
        assert "20240101" in pr_path

    # D1: Multiple repos
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d1_multiple_repos(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(repos=["org/a", "org/b", "org/c"])
        construct_data_files(data)
        assert mock_pp.call_count == 3
        assert mock_bd.call_count == 3

    # D8: Exception in print_pulls caught, continues to next repo
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d8_exception_caught_continues(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        mock_pp.side_effect = [RuntimeError("fail"), None]
        data = self._make_data(repos=["org/fail", "org/ok"])
        construct_data_files(data)  # should not raise
        # Second repo still processed
        assert mock_pp.call_count == 2

    # D4: Repo name with trailing comma stripped (comma must be at boundary)
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d4_repo_name_stripped(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        # .strip(",") then .strip() — comma must be at the edge, not after whitespace
        data = self._make_data(repos=[",org/repo,"])
        construct_data_files(data)
        call_args = mock_pp.call_args
        repo_arg = call_args[0][0]

    # D4: Repo name with leading/trailing whitespace stripped
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d4_repo_name_whitespace_stripped(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(repos=["  org/repo  "])
        construct_data_files(data)
        call_args = mock_pp.call_args
        repo_arg = call_args[0][0]
        assert repo_arg == "org/repo"

    # D4: Repo name with comma AND whitespace — strip(",") then strip() order matters
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d4_repo_name_comma_then_whitespace(self, mock_exists, mock_pp, mock_bd):
        """D4: BUG — strip(',').strip() only removes commas at the outermost boundary.
        Input ' ,org/repo, ' → strip(',') keeps commas (spaces at edge) → strip() → ',org/repo,'"""
        mock_exists.return_value = False
        data = self._make_data(repos=[" ,org/repo, "])
        construct_data_files(data)
        call_args = mock_pp.call_args
        repo_arg = call_args[0][0]
        assert repo_arg == ",org/repo,"

    # D1: max_pulls passed to print_pulls
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d1_max_pulls_passed(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(max_pulls=50)
        construct_data_files(data)
        _, kwargs = mock_pp.call_args
        assert kwargs.get("max_pulls") == 50

    # D2: Empty repos list — no calls
    @patch("swefficiency.collect.get_tasks_pipeline.build_dataset")
    @patch("swefficiency.collect.get_tasks_pipeline.print_pulls")
    @patch("swefficiency.collect.get_tasks_pipeline.os.path.exists")
    def test_d2_empty_repos(self, mock_exists, mock_pp, mock_bd):
        mock_exists.return_value = False
        data = self._make_data(repos=[])
        construct_data_files(data)
        mock_pp.assert_not_called()
        mock_bd.assert_not_called()


class TestMainPipeline:
    # D1: Basic execution with single token
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d1_single_token(self, mock_getenv, MockPool):
        mock_getenv.return_value = "token1"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        main(["org/repo"], "/tmp/prs", "/tmp/tasks")

        MockPool.assert_called_once_with(1)
        mock_pool.map.assert_called_once()

    # D1: Multiple tokens → Pool with correct size
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d1_multiple_tokens(self, mock_getenv, MockPool):
        mock_getenv.return_value = "tok1,tok2,tok3"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        main(["org/a", "org/b", "org/c"], "/tmp/prs", "/tmp/tasks")

        MockPool.assert_called_once_with(3)

    # D8: Missing GITHUB_TOKENS raises
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d8_missing_tokens_raises(self, mock_getenv):
        mock_getenv.return_value = None
        with pytest.raises(Exception, match="Missing GITHUB_TOKENS"):
            main(["org/repo"], "/tmp/prs", "/tmp/tasks")

    # D8: Empty GITHUB_TOKENS raises
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d8_empty_tokens_raises(self, mock_getenv):
        mock_getenv.return_value = ""
        with pytest.raises(Exception, match="Missing GITHUB_TOKENS"):
            main(["org/repo"], "/tmp/prs", "/tmp/tasks")

    # D1: max_pulls and cutoff_date forwarded
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d1_params_forwarded(self, mock_getenv, MockPool):
        mock_getenv.return_value = "tok1"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        main(
            ["org/repo"], "/tmp/prs", "/tmp/tasks", max_pulls=10, cutoff_date="20240101"
        )

        data_arg = mock_pool.map.call_args[0][1]
        assert data_arg[0]["max_pulls"] == 10
        assert data_arg[0]["cutoff_date"] == "20240101"

    # D7: Repos split across tokens correctly
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d7_repos_split_across_tokens(self, mock_getenv, MockPool):
        mock_getenv.return_value = "tok1,tok2"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        repos = ["org/a", "org/b", "org/c"]
        main(repos, "/tmp/prs", "/tmp/tasks")

        data_arg = mock_pool.map.call_args[0][1]
        assert len(data_arg) == 2
        all_repos = []
        for d in data_arg:
            all_repos.extend(d["repos"])
        assert sorted(all_repos) == sorted(repos)

    # D4: Token with trailing comma
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d4_token_trailing_comma(self, mock_getenv, MockPool):
        mock_getenv.return_value = "tok1,tok2,"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        main(["org/repo"], "/tmp/prs", "/tmp/tasks")

        # Trailing comma creates empty string token → Pool(3)
        MockPool.assert_called_once_with(3)

    # D1: Paths are absolutified
    @patch("swefficiency.collect.get_tasks_pipeline.Pool")
    @patch("swefficiency.collect.get_tasks_pipeline.os.getenv")
    def test_d1_paths_absolutified(self, mock_getenv, MockPool):
        mock_getenv.return_value = "tok1"
        mock_pool = MagicMock()
        MockPool.return_value.__enter__ = MagicMock(return_value=mock_pool)
        MockPool.return_value.__exit__ = MagicMock(return_value=False)

        main(["org/repo"], "relative/prs", "relative/tasks")

        data_arg = mock_pool.map.call_args[0][1]
        assert os.path.isabs(data_arg[0]["path_prs"])
        assert os.path.isabs(data_arg[0]["path_tasks"])



# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: split_instances  (D1/D2/D3/D11)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveSplitInstancesExpanded:
    """D1/D2/D3/D11: Exhaustive partitioning tests."""

    @pytest.mark.parametrize("size", list(range(1, 201)))
    def test_split_into_1_partition(self, size):
        """D1/BVA: Lists 1-200 split into 1 partition."""
        items = list(range(size))
        result = split_instances(items, 1)
        assert len(result) == 1
        assert result[0] == items

    @pytest.mark.parametrize("size", list(range(1, 101)))
    def test_split_into_equal_parts(self, size):
        """D1: Lists 1-100 split into size parts."""
        items = list(range(size))
        result = split_instances(items, size)
        assert len(result) == size
        all_items = [x for s in result for x in s]
        assert sorted(all_items) == items

    @pytest.mark.parametrize("n", list(range(1, 101)))
    def test_1000_items_split_n_ways(self, n):
        """D11: 1000 items split 1-100 ways."""
        items = list(range(1000))
        result = split_instances(items, n)
        assert len(result) == n
        all_items = [x for s in result for x in s]
        assert sorted(all_items) == items
        sizes = [len(s) for s in result]
        assert max(sizes) - min(sizes) <= 1

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_empty_list_n_ways(self, n):
        """D2: Empty list split 1-50 ways."""
        result = split_instances([], n)
        assert len(result) == n
        assert all(len(s) == 0 for s in result)

    @pytest.mark.parametrize("size", [1, 2, 3, 5, 10, 20, 50, 100])
    @pytest.mark.parametrize("n", [1, 2, 3, 5, 7, 10, 13, 17, 19, 23])
    def test_size_n_cross_product(self, size, n):
        """D1: Cross-product of sizes and split counts."""
        items = list(range(size))
        result = split_instances(items, n)
        assert len(result) == n
        all_items = [x for s in result for x in s]
        assert sorted(all_items) == items

    @pytest.mark.parametrize(
        "items",
        [
            list(range(10)),
            list("abcdefghij"),
            [None] * 10,
            [True, False] * 5,
            [(i, i + 1) for i in range(10)],
            [{"k": i} for i in range(10)],
            [[i] for i in range(10)],
            [float(i) for i in range(10)],
            [str(i) for i in range(10)],
            [complex(i, i) for i in range(10)],
        ],
    )
    def test_various_element_types_preserved(self, items):
        """D3: Various types preserved through split."""
        result = split_instances(items, 3)
        all_items = [x for s in result for x in s]
        assert len(all_items) == len(items)
