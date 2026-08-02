"""In-pipeline dynamic validation gate for the kwok backend.

Mocks the docker CLI at the subprocess boundary (build + run), then drives
``_run_validation_gate`` through each verdict branch to prove the gate:

  * accepts when golden reward >= min_golden AND empty reward <= max_empty,
  * rejects with ``all_tests_failed_validation_gate_golden_*`` when golden
    reward falls below the threshold,
  * rejects with ``all_tests_failed_validation_gate_empty_*`` when the empty
    stub scores too high (tests are non-discriminative),
  * short-circuits with ``validation_gate_timeout_*`` on container timeouts,
  * degrades to skipped=True when docker is unavailable,
  * exposes the four new CodeInstructOptions with sane kwok defaults.
"""

from __future__ import annotations

import subprocess

import pytest

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.spec.options import CodeInstructOptions


def _kwok_opts(**overrides) -> CodeInstructOptions:
    base = {"mode": "cli_app", "cli_app_backend": "kwok"}
    base.update(overrides)
    return CodeInstructOptions(**base)


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _test_sh_stdout(reward: float, passed: int = 5, total: int = 5) -> str:
    """Byte-shape of what test.sh emits: pytest lines + reward summary line."""
    failed = total - passed
    tail = f"= {passed} passed"
    if failed:
        tail += f", {failed} failed"
    tail += " in 0.5s ="
    return f"{tail}\nreward={reward:.4f} parser=v2\n"


class TestOptionDefaults:
    def test_validation_gate_default_is_true(self) -> None:
        assert CodeInstructOptions(mode="cli_app").cli_app_validation_gate is True

    def test_validation_gate_timeout_default(self) -> None:
        assert CodeInstructOptions(mode="cli_app").cli_app_validation_timeout_sec == 300

    def test_validation_gate_min_golden_reward_default(self) -> None:
        assert CodeInstructOptions(
            mode="cli_app"
        ).cli_app_validation_min_golden_reward == pytest.approx(0.99)

    def test_validation_gate_max_empty_reward_default(self) -> None:
        assert CodeInstructOptions(
            mode="cli_app"
        ).cli_app_validation_max_empty_reward == pytest.approx(0.05)

    def test_validation_gate_min_reference_reward_default(self) -> None:
        assert CodeInstructOptions(
            mode="cli_app"
        ).cli_app_validation_min_reference_reward == pytest.approx(0.5)


class TestValidationGate:
    """_run_validation_gate with docker calls mocked at the subprocess boundary."""

    def _patch(
        self,
        monkeypatch,
        *,
        golden_reward: float = 1.0,
        empty_reward: float = 0.0,
        golden_timeout: bool = False,
        empty_timeout: bool = False,
        docker_available: bool = True,
        build_ok: bool = True,
    ) -> list[list[str]]:
        """Replace subprocess.run inside the module with a scripted driver.

        Sequence per invocation:
          1. `docker version`  → controls availability
          2. `docker build`    → controls build outcome
          3+ `docker run` ...  → alternates golden then empty (order matches call site)
        """
        calls: list[list[str]] = []
        run_idx = {"n": 0}

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["docker", "version"]:
                if not docker_available:
                    raise FileNotFoundError("docker")
                return _FakeCompleted(stdout="ok", returncode=0)
            if cmd[:2] == ["docker", "build"]:
                if not build_ok:
                    raise subprocess.CalledProcessError(1, cmd, stderr=b"build fail")
                return _FakeCompleted(stdout="built", returncode=0)
            if cmd[:2] == ["docker", "run"]:
                idx = run_idx["n"]
                run_idx["n"] = idx + 1
                is_golden = idx == 0
                if is_golden and golden_timeout:
                    raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))
                if not is_golden and empty_timeout:
                    raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))
                reward = golden_reward if is_golden else empty_reward
                return _FakeCompleted(stdout=_test_sh_stdout(reward), returncode=0)
            return _FakeCompleted(stdout="", returncode=0)

        monkeypatch.setattr(S.subprocess, "run", fake_run)
        S._DOCKER_IMAGE_CACHE.clear()
        return calls

    def _invoke(self, **overrides):
        params = {
            "dockerfile_content": "FROM scratch\n",
            "aux_files": {"tests/conftest.py": "", "tests/test_a.py": ""},
            "test_script": "#!/bin/bash\ntrue\n",
            "golden_shim": {"submission/kubectl": '#!/bin/bash\nexec kubectl "$@"\n'},
            "empty_stub": S._KWOK_EMPTY_STUB,
            "min_golden_reward": 0.99,
            "max_empty_reward": 0.05,
            "timeout_sec": 300,
        }
        params.update(overrides)
        return S._run_validation_gate(**params)

    def test_accepts_when_golden_perfect_and_empty_zero(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_reward=1.0, empty_reward=0.0)
        result = self._invoke()
        assert result.passed is True
        assert result.reason == "ok"
        assert result.golden_reward == pytest.approx(1.0)
        assert result.empty_reward == pytest.approx(0.0)
        assert result.skipped is False

    def test_rejects_when_golden_reward_below_threshold(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_reward=0.60, empty_reward=0.0)
        result = self._invoke()
        assert result.passed is False
        assert result.reason.startswith("all_tests_failed_validation_gate_golden_")
        assert "0.60" in result.reason
        assert result.golden_reward == pytest.approx(0.60)

    def test_rejects_when_empty_reward_above_threshold(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_reward=1.0, empty_reward=0.40)
        result = self._invoke()
        assert result.passed is False
        assert result.reason.startswith("all_tests_failed_validation_gate_empty_")
        assert "0.40" in result.reason
        assert result.empty_reward == pytest.approx(0.40)

    def test_skipped_when_docker_unavailable(self, monkeypatch) -> None:
        self._patch(monkeypatch, docker_available=False)
        result = self._invoke()
        assert result.skipped is True
        assert result.passed is False
        assert result.reason == "validation_gate_docker_unavailable"

    def test_reports_timeout_for_golden(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_timeout=True)
        result = self._invoke()
        assert result.passed is False
        assert result.reason == "validation_gate_timeout_golden"
        assert result.golden_summary == "TIMEOUT"

    def test_reports_timeout_for_empty(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_reward=1.0, empty_timeout=True)
        result = self._invoke()
        assert result.passed is False
        assert result.reason == "validation_gate_timeout_empty"
        assert result.empty_summary == "TIMEOUT"

    def test_mounts_golden_shim_then_empty_stub_in_order(self, monkeypatch) -> None:
        calls = self._patch(monkeypatch, golden_reward=1.0, empty_reward=0.0)
        self._invoke()
        run_cmds = [c for c in calls if c[:2] == ["docker", "run"]]
        assert len(run_cmds) == 2
        first_targets = [seg for seg in run_cmds[0] if "/workspace/submission/kubectl" in seg]
        second_targets = [seg for seg in run_cmds[1] if "/workspace/submission/kubectl" in seg]
        assert first_targets, "first run must mount the golden shim at submission/kubectl"
        assert second_targets, "second run must mount the empty stub at submission/kubectl"
        assert first_targets[0] != second_targets[0], "golden and empty must be distinct host paths"

    def test_edge_reward_exactly_at_thresholds_accepts(self, monkeypatch) -> None:
        self._patch(monkeypatch, golden_reward=0.99, empty_reward=0.05)
        result = self._invoke()
        assert result.passed is True
        assert result.reason == "ok"


class TestKwokEmptyStubShape:
    def test_empty_stub_maps_kubectl_path_to_noop_script(self) -> None:
        assert set(S._KWOK_EMPTY_STUB) == {"submission/kubectl"}
        body = S._KWOK_EMPTY_STUB["submission/kubectl"]
        assert body.startswith("#!"), "empty stub must be a shebanged script"
        assert "exit 0" in body


class TestValidationGateFourLegs:
    """3rd + 4th legs: golden_vendored (git apply + vendored go build) and
    reference_compiled (git apply + go build)."""

    def _patch4(
        self,
        monkeypatch,
        *,
        rewards: tuple[float, float, float, float] = (1.0, 0.0, 1.0, 0.6),
        run_returncodes: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> list[list[str]]:
        calls: list[list[str]] = []
        run_idx = {"n": 0}

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["docker", "version"]:
                return _FakeCompleted(stdout="ok", returncode=0)
            if cmd[:2] == ["docker", "build"]:
                return _FakeCompleted(stdout="built", returncode=0)
            if cmd[:2] == ["docker", "run"]:
                idx = run_idx["n"]
                run_idx["n"] = idx + 1
                rc = run_returncodes[idx]
                if rc != 0:
                    return _FakeCompleted(
                        stdout="pre_test_script failed\n", stderr="build error\n", returncode=rc
                    )
                reward = rewards[idx]
                return _FakeCompleted(stdout=_test_sh_stdout(reward), returncode=rc)
            return _FakeCompleted(stdout="", returncode=0)

        monkeypatch.setattr(S.subprocess, "run", fake_run)
        S._DOCKER_IMAGE_CACHE.clear()
        return calls

    def _invoke4(self, **overrides):
        params = {
            "dockerfile_content": "FROM scratch\n",
            "aux_files": {"tests/conftest.py": "", "tests/test_a.py": ""},
            "test_script": "#!/bin/bash\ntrue\n",
            "golden_shim": {"submission/kubectl": '#!/bin/bash\nexec kubectl "$@"\n'},
            "empty_stub": S._KWOK_EMPTY_STUB,
            "min_golden_reward": 0.99,
            "max_empty_reward": 0.05,
            "timeout_sec": 300,
            "golden_vendored_diff": "diff --git a/x b/x\n",
            "reference_diff": "diff --git a/y b/y\n",
            "min_reference_reward": 0.5,
        }
        params.update(overrides)
        return S._run_validation_gate(**params)

    def test_all_four_legs_accept_when_thresholds_met(self, monkeypatch) -> None:
        calls = self._patch4(monkeypatch, rewards=(1.0, 0.0, 1.0, 0.6))
        result = self._invoke4()
        assert result.passed is True
        assert result.reason == "ok"
        assert result.golden_reward == pytest.approx(1.0)
        assert result.empty_reward == pytest.approx(0.0)
        assert result.golden_vendored_reward == pytest.approx(1.0)
        assert result.reference_reward == pytest.approx(0.6)
        run_cmds = [c for c in calls if c[:2] == ["docker", "run"]]
        assert len(run_cmds) == 4, "gauntlet must fire exactly 4 docker runs"

    def test_reference_leg_pre_test_script_and_diff_mount(self, monkeypatch) -> None:
        calls = self._patch4(monkeypatch, rewards=(1.0, 0.0, 1.0, 0.6))
        self._invoke4()
        run_cmds = [c for c in calls if c[:2] == ["docker", "run"]]
        ref_cmd = run_cmds[3]
        joined = " ".join(ref_cmd)
        assert "/work/reference.diff" in joined, "ref leg must mount reference.diff"
        assert "git apply" in joined, "ref leg must git-apply the diff"
        assert "go build -o kubectl" in joined, "ref leg must compile submission/kubectl"

    def test_golden_vendored_leg_pre_test_script_and_diff_mount(self, monkeypatch) -> None:
        calls = self._patch4(monkeypatch, rewards=(1.0, 0.0, 1.0, 0.6))
        self._invoke4()
        run_cmds = [c for c in calls if c[:2] == ["docker", "run"]]
        gv_cmd = run_cmds[2]
        joined = " ".join(gv_cmd)
        assert "/work/golden.diff" in joined, "gv leg must mount golden.diff"
        assert "GOFLAGS=-mod=vendor" in joined, "gv leg must build against vendor tree"
        assert "cmd/kubectl" in joined, "gv leg must target ./cmd/kubectl"

    def test_rejects_when_golden_vendored_below_min_golden(self, monkeypatch) -> None:
        self._patch4(monkeypatch, rewards=(1.0, 0.0, 0.40, 0.6))
        result = self._invoke4()
        assert result.passed is False
        assert result.reason.startswith("all_tests_failed_validation_gate_golden_vendored_")
        assert "0.40" in result.reason

    def test_rejects_when_reference_below_min_reference(self, monkeypatch) -> None:
        self._patch4(monkeypatch, rewards=(1.0, 0.0, 1.0, 0.10))
        result = self._invoke4()
        assert result.passed is False
        assert result.reason.startswith("all_tests_failed_validation_gate_reference_")
        assert "0.10" in result.reason

    def test_rejects_on_golden_vendored_build_failure(self, monkeypatch) -> None:
        self._patch4(
            monkeypatch,
            rewards=(1.0, 0.0, 0.0, 0.6),
            run_returncodes=(0, 0, 1, 0),
        )
        result = self._invoke4()
        assert result.passed is False
        assert result.reason == "validation_gate_golden_vendored_build_failed"
        assert result.golden_vendored_summary == "BUILD_FAILED"

    def test_rejects_on_reference_build_failure(self, monkeypatch) -> None:
        self._patch4(
            monkeypatch,
            rewards=(1.0, 0.0, 1.0, 0.0),
            run_returncodes=(0, 0, 0, 1),
        )
        result = self._invoke4()
        assert result.passed is False
        assert result.reason == "validation_gate_reference_build_failed"
        assert result.reference_summary == "BUILD_FAILED"

    def test_skipping_new_legs_when_diffs_none(self, monkeypatch) -> None:
        calls = self._patch4(monkeypatch, rewards=(1.0, 0.0, 0.0, 0.0))
        result = self._invoke4(golden_vendored_diff=None, reference_diff=None)
        assert result.passed is True
        run_cmds = [c for c in calls if c[:2] == ["docker", "run"]]
        assert len(run_cmds) == 2, "with no diffs supplied, only legacy 2-leg runs"
