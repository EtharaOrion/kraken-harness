"""Diff-similarity reward function."""

from __future__ import annotations

import math

from repo2rlenv.reward import (
    ExecutionReport,
    _clamp_unit,
    calculate_diff_similarity_reward,
)

SAMPLE_DIFF = """diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def hello():
-    return "hello"
+    return "hello, world"
"""


def test_identical_diffs_yield_one():
    reward, meta = calculate_diff_similarity_reward(SAMPLE_DIFF, SAMPLE_DIFF)
    assert reward == 1.0
    assert meta.parse_error is None


def test_empty_prediction_yields_zero():
    reward, meta = calculate_diff_similarity_reward(SAMPLE_DIFF, "")
    assert reward == 0.0
    assert meta.parse_error == "empty prediction"


def test_normalization_ignores_index_and_hunk_numbers():
    """Two diffs that differ only in volatile metadata should still score 1.0."""
    a = """diff --git a/x.py b/x.py
index 1234567..89abcde 100644
--- a/x.py
+++ b/x.py
@@ -1,5 +1,5 @@
 a
-b
+B
 c
"""
    b = """diff --git a/x.py b/x.py
index ffffff0..0000fff 100644
--- a/x.py
+++ b/x.py
@@ -42,5 +42,5 @@
 a
-b
+B
 c
"""
    reward, _ = calculate_diff_similarity_reward(a, b)
    assert reward == 1.0


def test_unrelated_diffs_score_low():
    a = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-print("hello")
+print("HELLO")
"""
    b = """diff --git a/bar.py b/bar.py
--- a/bar.py
+++ b/bar.py
@@ -1,1 +1,1 @@
-import os
+import sys
"""
    reward, _ = calculate_diff_similarity_reward(a, b)
    assert reward < 0.5


def test_partial_match_scores_in_between():
    a = SAMPLE_DIFF
    b = SAMPLE_DIFF.replace("hello, world", "goodbye")
    reward, _ = calculate_diff_similarity_reward(a, b)
    assert 0.5 < reward < 1.0


def test_clamp_unit_bounds_out_of_range_and_nonfinite():
    assert _clamp_unit(-1.0) == 0.0
    assert _clamp_unit(2.0) == 1.0
    assert _clamp_unit(0.5) == 0.5
    assert _clamp_unit(0.0) == 0.0
    assert _clamp_unit(1.0) == 1.0
    assert _clamp_unit(float("nan")) == 0.0
    assert _clamp_unit(float("inf")) == 1.0
    assert _clamp_unit(float("-inf")) == 0.0


def test_diff_reward_always_in_unit_interval_for_adversarial_inputs():
    cases = [
        ("diff x", ""),
        ("", "diff x"),
        ("", ""),
        ("diff x", "   \n  "),
        ("a\nb\nc", "a\nb\nc"),
        ("aaa", "zzz"),
        ("a", "x\n" * 10000),
        ("\x00\x01\x02", "\xff\xfe"),
        ("caf\u00e9\n\u2014\n", "cafe\n-\n"),
    ]
    for oracle, pred in cases:
        reward, _ = calculate_diff_similarity_reward(oracle, pred)
        assert 0.0 <= reward <= 1.0
        assert math.isfinite(reward)


def test_execution_report_rates_always_in_unit_interval():
    cases = [
        ExecutionReport([], [], [], []),
        ExecutionReport(["a", "b"], [], [], []),
        ExecutionReport([], ["a", "b"], [], []),
        ExecutionReport(["a"], [], ["k1"], ["k2"]),
        ExecutionReport(["a"], ["b"], ["k1", "k2"], ["k3"]),
    ]
    for report in cases:
        assert 0.0 <= report.f2p_rate <= 1.0
        assert 0.0 <= report.p2p_rate <= 1.0
