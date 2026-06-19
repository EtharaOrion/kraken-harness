"""Runner-level fixes from PR #2 review (codex P1/P2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from repo2rlenv.bootstrap import cache as cache_mod
from repo2rlenv.bootstrap import runner
from repo2rlenv.bootstrap.agent import AgentAction, AgentTurn
from repo2rlenv.bootstrap.runner import (
    BootstrapError,
    _check_bootstrap_cache,
    _ensure_git_in_image,
    _make_image_tag,
    _push_and_resolve_digest,
    _resolve_language_and_base_image,
    _resolve_repo_digest,
    _run_smoke_gate,
    _safe_emit,
    _save_agent_transcript,
    _scrub_token,
    _shallow_clone_at_ref,
)
from repo2rlenv.bootstrap.spec import LanguageHint


def test_scrub_token_replaces_secret():
    # Deliberately do NOT use the canonical "user:pass@host" Basic Auth shape here:
    # GitGuardian's secret-pattern detector matches that exact form even when the
    # value is obviously a fake placeholder, which blocks CI for no real reason.
    # The function we're testing is content-agnostic — it does string replace.
    fake_token = "PLACEHOLDER_TEST_TOKEN_VALUE"
    msg = f"fatal: git operation failed (token redacted: {fake_token})"
    assert fake_token not in _scrub_token(msg, fake_token)
    assert "***" in _scrub_token(msg, fake_token)


def test_scrub_token_passthrough_when_no_token():
    msg = "fatal: nothing"
    assert _scrub_token(msg, None) == msg


def test_shallow_clone_head_uses_plain_clone(tmp_path: Path):
    """ref='HEAD' must NOT pass --branch (it'd be interpreted as a branch named 'HEAD')."""
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
        _shallow_clone_at_ref(
            "https://github.com/owner/name",
            "HEAD",
            None,
            tmp_path / "out",
        )
        args = run.call_args_list[0].args[0]
        assert "--branch" not in args


def test_shallow_clone_branch_tries_clone_branch_first(tmp_path: Path):
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
        _shallow_clone_at_ref(
            "https://github.com/owner/name",
            "release-1.0",
            None,
            tmp_path / "out",
        )
        args = run.call_args_list[0].args[0]
        assert "--branch" in args
        idx = args.index("--branch")
        assert args[idx + 1] == "release-1.0"


def test_shallow_clone_falls_back_to_fetch_on_sha(tmp_path: Path):
    """When --branch <sha> fails, fall back to clone-no-checkout + fetch + checkout."""
    call_sequence = []

    def fake_run(cmd, **kwargs):
        call_sequence.append(cmd)
        # First call (clone --branch) fails with 128 (typical for SHA)
        if "--branch" in cmd:
            return mock.Mock(returncode=128, stderr="not found", stdout="")
        # Subsequent calls succeed
        return mock.Mock(returncode=0, stderr="", stdout="")

    with mock.patch("subprocess.run", side_effect=fake_run):
        _shallow_clone_at_ref(
            "https://github.com/owner/name",
            "a1b2c3d4e5f6",
            None,
            tmp_path / "out",
        )
    # Should have: clone --branch (failed), clone --no-checkout, fetch, checkout
    all_args = [arg for cmd in call_sequence for arg in cmd]
    assert "--branch" in all_args, "should have attempted clone --branch first"
    assert "fetch" in all_args, "fallback should `git fetch origin <ref>`"
    assert "checkout" in all_args, "fallback should `git checkout <ref>`"


def test_resolve_repo_digest_parses_inspect_output():
    """Should return the first RepoDigests entry post-push."""
    inspect_out = '["ghcr.io/owner/foo@sha256:abc123"]'
    with mock.patch.object(runner, "_run") as run:
        run.return_value = mock.Mock(ok=True, stdout=inspect_out)
        digest = _resolve_repo_digest("ghcr.io/owner/foo:abc")
    assert digest == "ghcr.io/owner/foo@sha256:abc123"


def test_resolve_repo_digest_returns_none_when_unpushed():
    """No RepoDigests yet → returns None so caller keeps the local Id."""
    with mock.patch.object(runner, "_run") as run:
        run.return_value = mock.Mock(ok=True, stdout="[]")
        assert _resolve_repo_digest("local/foo:bar") is None


def test_resolve_repo_digest_returns_none_on_inspect_fail():
    with mock.patch.object(runner, "_run") as run:
        run.return_value = mock.Mock(ok=False, stdout="")
        assert _resolve_repo_digest("missing:tag") is None


def test_user_dockerfile_missing_path_raises(tmp_path: Path):
    """Pointing user_dockerfile at a non-existent file is a clear error."""
    from repo2rlenv.spec.input import AuthSpec, BootstrapSpec, LLMSpec, RepoSpec

    repo = RepoSpec(url="owner/name", access="public")
    spec = BootstrapSpec(user_dockerfile=tmp_path / "does-not-exist.Dockerfile")
    llm = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")

    # Stub out the bits that would otherwise fail before we hit the dockerfile check
    with (
        mock.patch.object(runner, "is_docker_available", return_value=True),
        mock.patch.object(runner, "_shallow_clone_at_ref"),
        mock.patch.object(runner, "_resolve_head_sha", return_value="a" * 40),
    ):
        with pytest.raises(BootstrapError, match="user_dockerfile not found"):
            runner.ensure_bootstrap(repo, spec, llm, AuthSpec())


def test_reconstructed_dockerfile_is_rebuildable():
    """Reconstructed Dockerfile must COPY the repo before agent RUNs.

    The agent runs commands inside /workspace where the repo already exists;
    `pip install -e .` etc. assume repo files in CWD. A Dockerfile that only
    replays RUN lines without COPY would fail immediately on rebuild.
    """
    from repo2rlenv.bootstrap.runner import _reconstruct_dockerfile

    class FakeAction:
        def __init__(self, name, input):
            self.name = name
            self.input = input

    class FakeTurn:
        def __init__(self, action):
            self.action = action

    turns = [
        FakeTurn(FakeAction("BASH", "pip install -e .")),
        FakeTurn(FakeAction("BASH", "pytest --collect-only")),
        FakeTurn(FakeAction("READ_FILE", "/workspace/setup.py")),  # non-BASH skipped
    ]
    dockerfile = _reconstruct_dockerfile("python:3.12-slim", turns)
    assert "FROM python:3.12-slim" in dockerfile
    workdir_idx = dockerfile.index("WORKDIR /workspace")
    copy_idx = dockerfile.index("COPY . /workspace")
    first_run_idx = dockerfile.index("RUN pip install")
    assert workdir_idx < first_run_idx and copy_idx < first_run_idx, (
        "WORKDIR + COPY must precede any RUN line"
    )
    # Non-BASH actions should not become RUN lines
    assert "READ_FILE" not in dockerfile


def test_scrub_clone_credentials_strips_token(tmp_path: Path):
    """After cloning with a token, .git/config should not retain the token."""
    import subprocess as sp

    from repo2rlenv.bootstrap.runner import _scrub_clone_credentials

    fake_token = "PLACEHOLDER_TEST_TOKEN_VALUE"
    bare_url = "https://github.com/owner/name"
    auth_url = f"https://x-access-token:{fake_token}@github.com/owner/name"

    clone_dir = tmp_path / "repo"
    clone_dir.mkdir()
    sp.run(["git", "init", "-q"], cwd=clone_dir, check=True)
    sp.run(["git", "remote", "add", "origin", auth_url], cwd=clone_dir, check=True)

    config = (clone_dir / ".git" / "config").read_text()
    assert fake_token in config

    _scrub_clone_credentials(clone_dir, bare_url)

    config = (clone_dir / ".git" / "config").read_text()
    assert fake_token not in config, "scrub must remove the embedded token"
    assert bare_url in config, "remote URL should now be the clean form"


def test_safe_emit_calls_callback():
    calls = []
    _safe_emit(lambda p, d: calls.append((p, d)), "started", {"k": 1})
    assert calls == [("started", {"k": 1})]


def test_safe_emit_swallows_exception():
    def boom(phase, details):
        raise RuntimeError("oops")

    _safe_emit(boom, "started")


def test_safe_emit_noop_when_none():
    _safe_emit(None, "started")


def test_safe_emit_defaults_details_to_empty_dict():
    calls = []
    _safe_emit(lambda p, d: calls.append(d), "started")
    assert calls == [{}]


def test_make_image_tag_with_registry():
    repo = mock.Mock()
    repo.owner_name = ("acme", "myrepo")
    spec = mock.Mock()
    spec.image_registry = "ghcr.io/acme"
    tag = _make_image_tag(repo, spec, "abc123def456789")
    assert tag == "ghcr.io/acme/acme__myrepo:abc123def456"


def test_make_image_tag_without_registry():
    repo = mock.Mock()
    repo.owner_name = ("owner", "name")
    spec = mock.Mock()
    spec.image_registry = None
    tag = _make_image_tag(repo, spec, "deadbeef123456")
    assert tag == "local/r2e-bootstrap/owner__name:deadbeef1234"


def test_run_smoke_gate_empty_cmds():
    assert _run_smoke_gate(mock.Mock(), []) is True


@pytest.mark.parametrize("exit_code", [0, 1, 5])
def test_run_smoke_gate_acceptable_codes(exit_code):
    sandbox = mock.Mock()
    sandbox.exec.return_value = mock.Mock(exit_code=exit_code)
    assert _run_smoke_gate(sandbox, ["pytest"]) is True


def test_run_smoke_gate_env_broken():
    sandbox = mock.Mock()
    sandbox.exec.return_value = mock.Mock(exit_code=2)
    assert _run_smoke_gate(sandbox, ["pytest"]) is False


def test_run_smoke_gate_joins_commands():
    sandbox = mock.Mock()
    sandbox.exec.return_value = mock.Mock(exit_code=0)
    _run_smoke_gate(sandbox, ["pip install -e .", "pytest"])
    cmd = sandbox.exec.call_args[0][0]
    assert cmd == "pip install -e . && pytest"


def test_save_agent_transcript_writes_jsonl(tmp_path: Path):
    turns = [
        AgentTurn(
            step=1,
            thought="install deps",
            action=AgentAction(name="BASH", input="pip install -e ."),
            observation="ok",
        ),
        AgentTurn(
            step=2,
            thought="run tests",
            action=AgentAction(name="BASH", input="pytest"),
            observation="passed",
        ),
    ]
    slot = tmp_path / "slot"
    _save_agent_transcript(turns, slot)
    content = (slot / "transcript.jsonl").read_text().strip().split("\n")
    assert len(content) == 2
    first = json.loads(content[0])
    assert first["step"] == 1
    assert first["action"] == "BASH"
    assert first["input"] == "pip install -e ."
    assert first["thought"] == "install deps"
    assert first["observation"] == "ok"


def test_save_agent_transcript_creates_dirs(tmp_path: Path):
    turns = [
        AgentTurn(
            step=1,
            thought="t",
            action=AgentAction(name="BASH", input="x"),
            observation="o",
        ),
    ]
    deep = tmp_path / "a" / "b" / "c"
    _save_agent_transcript(turns, deep)
    assert (deep / "transcript.jsonl").exists()


def test_save_agent_transcript_handles_oserror(tmp_path: Path):
    turns = [
        AgentTurn(
            step=1,
            thought="t",
            action=AgentAction(name="BASH", input="x"),
            observation="o",
        ),
    ]
    slot = tmp_path / "slot"
    slot.mkdir()
    with mock.patch("builtins.open", side_effect=OSError("read-only")):
        _save_agent_transcript(turns, slot)


def test_check_bootstrap_cache_hit():
    cached = mock.Mock()
    cached.image_digest = "sha256:abc"
    phases = []
    with mock.patch.object(cache_mod, "load", return_value=cached):
        result = _check_bootstrap_cache(
            "owner/repo",
            "abc123",
            Path("/cache"),
            {},
            lambda p, d: phases.append(p),
        )
    assert result is cached
    assert "pull_skipped" in phases
    assert "push_skipped" in phases


def test_check_bootstrap_cache_miss():
    with mock.patch.object(cache_mod, "load", return_value=None):
        result = _check_bootstrap_cache(
            "owner/repo",
            "abc123",
            Path("/cache"),
            {},
            lambda p, d: None,
        )
    assert result is None


def test_check_bootstrap_cache_no_digest():
    """Cache hit but missing image_digest should be treated as a miss."""
    cached = mock.Mock()
    cached.image_digest = ""
    with mock.patch.object(cache_mod, "load", return_value=cached):
        result = _check_bootstrap_cache(
            "owner/repo",
            "abc123",
            Path("/cache"),
            {},
            lambda p, d: None,
        )
    assert result is None


def test_ensure_git_in_image_present():
    sandbox = mock.Mock()
    sandbox.exec.return_value = mock.Mock(ok=True, stdout="OK")
    emit = mock.Mock()
    _ensure_git_in_image(sandbox, emit)
    sandbox.exec.assert_called_once()
    emit.assert_not_called()


def test_ensure_git_in_image_installs():
    check = mock.Mock(ok=False, stdout="")
    install = mock.Mock(ok=True, exit_code=0)
    sandbox = mock.Mock()
    sandbox.exec.side_effect = [check, install]
    emit = mock.Mock()
    _ensure_git_in_image(sandbox, emit)
    assert sandbox.exec.call_count == 2
    emit.assert_called_once_with("git_install", {"detail": "ensuring git in image"})


def test_resolve_language_and_base_image_with_hint():
    spec = mock.Mock()
    spec.languages_hint = ["python"]
    spec.base_image = None
    emit = mock.Mock()
    with mock.patch.object(runner, "base_image_for", return_value="python:3.12-slim"):
        lang, image = _resolve_language_and_base_image(spec, Path("/clone"), emit)
    assert lang == LanguageHint.PYTHON
    assert image == "python:3.12-slim"
    emit.assert_called_once()


def test_resolve_language_and_base_image_auto_detect():
    spec = mock.Mock()
    spec.languages_hint = []
    spec.base_image = "custom:latest"
    emit = mock.Mock()
    with mock.patch.object(runner, "detect_language", return_value=LanguageHint.GO):
        lang, image = _resolve_language_and_base_image(spec, Path("/clone"), emit)
    assert lang == LanguageHint.GO
    assert image == "custom:latest"


def test_resolve_language_and_base_image_invalid_hint_falls_back():
    spec = mock.Mock()
    spec.languages_hint = ["not_a_real_language"]
    spec.base_image = None
    emit = mock.Mock()
    with (
        mock.patch.object(runner, "detect_language", return_value=LanguageHint.RUST),
        mock.patch.object(runner, "base_image_for", return_value="rust:1.78"),
    ):
        lang, image = _resolve_language_and_base_image(spec, Path("/clone"), emit)
    assert lang == LanguageHint.RUST
    assert image == "rust:1.78"


def test_push_and_resolve_digest_no_registry():
    spec = mock.Mock()
    spec.image_registry = None
    phases = []
    pushed, digest = _push_and_resolve_digest(
        mock.Mock(),
        "tag:v1",
        "sha256:orig",
        spec,
        lambda p, d: phases.append(p),
    )
    assert not pushed
    assert digest == "sha256:orig"
    assert "push_skipped" in phases


def test_push_and_resolve_digest_registry_no_slash():
    """Registry without '/' is treated as no registry."""
    spec = mock.Mock()
    spec.image_registry = "localonly"
    phases = []
    pushed, _digest = _push_and_resolve_digest(
        mock.Mock(),
        "tag:v1",
        "sha256:orig",
        spec,
        lambda p, d: phases.append(p),
    )
    assert not pushed
    assert "push_skipped" in phases


def test_push_and_resolve_digest_success():
    spec = mock.Mock()
    spec.image_registry = "ghcr.io/owner"
    sandbox = mock.Mock()
    sandbox.push.return_value = True
    phases = []
    with mock.patch.object(
        runner,
        "_resolve_repo_digest",
        return_value="ghcr.io/owner/r@sha256:new123",
    ):
        pushed, digest = _push_and_resolve_digest(
            sandbox,
            "tag:v1",
            "sha256:orig",
            spec,
            lambda p, d: phases.append(p),
        )
    assert pushed
    assert digest == "ghcr.io/owner/r@sha256:new123"
    assert "push_start" in phases
    assert "push_done" in phases


def test_push_and_resolve_digest_push_fails():
    spec = mock.Mock()
    spec.image_registry = "ghcr.io/owner"
    sandbox = mock.Mock()
    sandbox.push.return_value = False
    phases = []
    pushed, digest = _push_and_resolve_digest(
        sandbox,
        "tag:v1",
        "sha256:orig",
        spec,
        lambda p, d: phases.append(p),
    )
    assert not pushed
    assert digest == "sha256:orig"
    assert "push_failed" in phases
