"""Unit tests for the anti-reward-hacking oracle scanner (G8 guard).

Pure AST analysis: no Docker, LLM, or network. Feeds crafted oracle sources to
:func:`scan_oracle_for_reward_hacking` and asserts each finding code, plus the
false-positive guards (localhost / 127.0.0.1 and the exempt S3 xmlns URI).
"""

from __future__ import annotations

from repo2rlenv.pipelines._cli_app_antihack import (
    blocked_host_literals,
    scan_oracle_for_reward_hacking,
)


def test_clean_stdlib_oracle_has_no_findings() -> None:
    src = (
        "import urllib.request\n"
        "with open('payload.bin', 'rb') as f:\n"
        "    data = f.read()\n"
        "urllib.request.urlopen('http://127.0.0.1:8000/', data=data)\n"
        "urllib.request.urlopen('http://localhost:9000/upload')\n"
    )
    assert scan_oracle_for_reward_hacking(src) == []


def test_forbidden_import_flags_sdk_roots() -> None:
    assert "forbidden_import" in scan_oracle_for_reward_hacking("import boto3")
    from_import = scan_oracle_for_reward_hacking("from botocore.client import BaseClient")
    assert "forbidden_import" in from_import
    # stdlib imports are always fine
    assert scan_oracle_for_reward_hacking("import urllib.request\nimport json") == []


def test_reads_test_artifacts() -> None:
    direct = scan_oracle_for_reward_hacking("open('conftest.py')")
    assert "reads_test_artifacts" in direct
    via_pathlib = scan_oracle_for_reward_hacking(
        "import pathlib\npathlib.Path('tests/data.json').read_text()"
    )
    assert "reads_test_artifacts" in via_pathlib


def test_writes_grading_artifacts() -> None:
    positional = scan_oracle_for_reward_hacking("open('/logs/verifier/reward.json', 'w')")
    assert "writes_grading_artifacts" in positional
    keyword = scan_oracle_for_reward_hacking("open('/logs/verifier/reward.txt', mode='w')")
    assert "writes_grading_artifacts" in keyword
    write_text = scan_oracle_for_reward_hacking(
        "import pathlib\npathlib.Path('reward.json').write_text('1.0')"
    )
    assert "writes_grading_artifacts" in write_text


def test_shells_real_aws() -> None:
    as_list = scan_oracle_for_reward_hacking(
        "import subprocess\nsubprocess.run(['aws', 's3', 'ls'])"
    )
    assert "shells_real_aws" in as_list
    as_system = scan_oracle_for_reward_hacking("import os\nos.system('aws s3 ls')")
    assert "shells_real_aws" in as_system
    as_module = scan_oracle_for_reward_hacking(
        "import subprocess\nsubprocess.Popen(['python', '-m', 'awscli'])"
    )
    assert "shells_real_aws" in as_module


def test_network_disallowed_public_ip() -> None:
    with_scheme = scan_oracle_for_reward_hacking("url = 'http://8.8.8.8/upload'")
    assert "network_disallowed_host" in with_scheme
    bare = scan_oracle_for_reward_hacking("host = '8.8.8.8'")
    assert "network_disallowed_host" in bare


def test_findings_are_sorted_and_deduped() -> None:
    src = "import boto3\nimport subprocess\nsubprocess.run(['aws', 's3', 'ls'])\n"
    assert scan_oracle_for_reward_hacking(src) == [
        "forbidden_import",
        "shells_real_aws",
    ]


def test_syntax_error_source_is_ignored() -> None:
    assert scan_oracle_for_reward_hacking("def broken(:") == []
    assert blocked_host_literals("def broken(:") == []


def test_blocked_host_literals_exempts_s3_xmlns_identifier() -> None:
    src = "NS = 'http://s3.amazonaws.com/doc/2006-03-01/'"
    assert blocked_host_literals(src) == []


def test_blocked_host_literals_reports_offender() -> None:
    assert blocked_host_literals("u = 'http://8.8.8.8/x'") == ["http://8.8.8.8/x"]
