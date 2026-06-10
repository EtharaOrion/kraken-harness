"""Token resolution paths."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

from repo2rlenv.auth import (
    git_credentials_env,
    resolve_github_token,
    resolve_hf_token,
    resolve_llm_api_key,
)
from repo2rlenv.spec.input import AuthSpec, RepoSpec


def test_explicit_env_wins():
    repo = RepoSpec(url="huggingface/trl", auth_token_env="MY_PRIVATE_PAT")
    auth = AuthSpec(use_gh_cli=True)
    with mock.patch.dict(os.environ, {"MY_PRIVATE_PAT": "explicit-token"}):
        assert resolve_github_token(repo, auth) == "explicit-token"


def test_falls_through_to_env_var_when_gh_disabled():
    repo = RepoSpec(url="huggingface/trl")
    auth = AuthSpec(use_gh_cli=False, github_token_env="GITHUB_TOKEN")
    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}, clear=False):
        assert resolve_github_token(repo, auth) == "env-token"


def test_returns_none_when_nothing_set():
    repo = RepoSpec(url="huggingface/trl")
    auth = AuthSpec(use_gh_cli=False, github_token_env="ABSENT_VAR")
    with mock.patch.dict(os.environ, {}, clear=True):
        assert resolve_github_token(repo, auth) is None


def test_git_credentials_env_with_token_sets_askpass_helper():
    token = "ghp_test_token_value"
    with git_credentials_env(token) as env:
        assert env["GIT_TOKEN"] == token
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        askpass = env["GIT_ASKPASS"]
        askpass_path = Path(askpass)
        assert askpass_path.exists()
        assert askpass_path.stat().st_mode & 0o700
        script_body = askpass_path.read_text()
        assert token not in script_body
        assert "$GIT_TOKEN" in script_body

        user_proc = subprocess.run(
            [askpass, "Username for 'https://github.com':"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
            check=False,
        )
        assert user_proc.returncode == 0
        assert user_proc.stdout.strip() == "x-access-token"

        pass_proc = subprocess.run(
            [askpass, "Password for 'https://x-access-token@github.com':"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
            check=False,
        )
        assert pass_proc.returncode == 0
        assert pass_proc.stdout.strip() == token

    assert not askpass_path.exists()


def test_git_credentials_env_without_token_passes_env_through():
    with mock.patch.dict(os.environ, {"PATH": "/test/path"}, clear=True):
        with git_credentials_env(None) as env:
            assert "GIT_ASKPASS" not in env
            assert "GIT_TOKEN" not in env
            assert env["PATH"] == "/test/path"


def test_llm_api_key_resolution_uses_provider_default():
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-xxx"}):
        assert resolve_llm_api_key("anthropic") == "sk-ant-xxx"


def test_llm_api_key_resolution_explicit_env():
    with mock.patch.dict(os.environ, {"MY_KEY": "custom"}):
        assert resolve_llm_api_key("anthropic", "MY_KEY") == "custom"


def test_llm_api_key_resolution_bedrock_is_unmapped_by_design():
    # Bedrock is intentionally NOT in the provider->env-var map: its creds
    # (AWS_BEARER_TOKEN_BEDROCK or AWS_ACCESS_KEY_ID/SECRET/REGION) are read by
    # litellm/boto3 from the env, never passed as an api_key. So even with a
    # bearer token present, resolve_llm_api_key returns None — and _do_complete
    # must not hard-fail for it (see ENV_AUTH_PROVIDERS).
    with mock.patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "bdrk-xxx"}, clear=True):
        assert resolve_llm_api_key("bedrock") is None


def test_hf_token_falls_back_to_env():
    with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_xxx"}, clear=True):
        # Patch the cache file path so we don't accidentally pick up real cache
        auth = AuthSpec(use_hf_cli=False)
        assert resolve_hf_token(auth) == "hf_xxx"
