"""In-pipeline docker gauntlet gate for the kwok backend.

Mocks ``_run_docker_gauntlet_g3g4`` (never spawns docker) and drives
``_run_g3g4_gauntlet_gate`` through each branch to prove the gate:

  * enforces ``empty==0 && oracle==1`` for kwok tasks,
  * emits the kwok-specific reject taxonomy (empty_pass_too_high /
    oracle_pass_too_low / startup_failed),
  * flips the ``cli_app_docker_gauntlet`` default to True so kwok tasks are
    gated by default,
  * bumps ``cli_app_docker_timeout_sec`` to 480 to accommodate kwokctl boot.
"""

from __future__ import annotations

import pytest

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.spec.options import CodeInstructOptions


def _kwok_opts(**overrides) -> CodeInstructOptions:
    base = {"mode": "cli_app", "cli_app_backend": "kwok"}
    base.update(overrides)
    return CodeInstructOptions(**base)


class TestOptionDefaults:
    def test_docker_gauntlet_default_is_true(self) -> None:
        opts = CodeInstructOptions(mode="cli_app")
        assert opts.cli_app_docker_gauntlet is True

    def test_docker_gauntlet_default_true_for_kwok_backend(self) -> None:
        opts = _kwok_opts()
        assert opts.cli_app_docker_gauntlet is True

    def test_docker_timeout_default_is_480_seconds(self) -> None:
        opts = CodeInstructOptions(mode="cli_app")
        assert opts.cli_app_docker_timeout_sec == 480

    def test_docker_empty_pass_max_unchanged(self) -> None:
        opts = CodeInstructOptions(mode="cli_app")
        assert opts.cli_app_docker_empty_pass_max == 0.05

    def test_docker_oracle_pass_min_unchanged(self) -> None:
        opts = CodeInstructOptions(mode="cli_app")
        assert opts.cli_app_docker_oracle_pass_min == 1.0


class TestGauntletGateKwokVerdicts:
    def _call_gate(self, monkeypatch, gauntlet_result: dict, *, task_id: str = "task-xyz"):
        monkeypatch.setattr(
            S,
            "_run_docker_gauntlet_g3g4",
            lambda **kw: gauntlet_result,
        )
        opts = _kwok_opts()
        return S._run_g3g4_gauntlet_gate(
            options=opts,
            dockerfile="FROM scratch\n",
            aux_files={"tests/conftest.py": "", "tests/test_dummy.py": ""},
            test_script="#!/bin/bash\ntrue\n",
            oracle_code="print('oracle')\n",
            task_id=task_id,
        )

    def test_accepts_when_empty_zero_and_oracle_perfect(self, monkeypatch, caplog) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.0,
            "g3_empty_passed": 0,
            "g3_empty_total": 5,
            "g3_pass": True,
            "g4_oracle_pass_rate": 1.0,
            "g4_oracle_passed": 5,
            "g4_oracle_total": 5,
            "g4_pass": True,
        }
        with caplog.at_level("INFO", logger=S.logger.name):
            out = self._call_gate(monkeypatch, result)
        assert out is result
        joined = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "gauntlet kwok task task-xyz" in joined
        assert "verdict=accept" in joined
        assert "empty_reward=0.00" in joined
        assert "oracle_reward=1.00" in joined

    def test_rejects_when_empty_stub_passes_too_many(self, monkeypatch, caplog) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.4,
            "g3_empty_passed": 2,
            "g3_empty_total": 5,
            "g3_pass": False,
            "g4_oracle_pass_rate": 1.0,
            "g4_oracle_passed": 5,
            "g4_oracle_total": 5,
            "g4_pass": True,
        }
        with caplog.at_level("INFO", logger=S.logger.name):
            with pytest.raises(S._TaskRejected) as exc:
                self._call_gate(monkeypatch, result)
        assert exc.value.reason.startswith("docker_gauntlet_kwok_empty_pass_too_high")
        assert "0.40" in exc.value.reason
        assert any("verdict=reject" in r.getMessage() for r in caplog.records)
        assert any("empty_reward=0.40" in r.getMessage() for r in caplog.records)

    def test_rejects_when_oracle_underperforms(self, monkeypatch, caplog) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.0,
            "g3_empty_passed": 0,
            "g3_empty_total": 5,
            "g3_pass": True,
            "g4_oracle_pass_rate": 0.6,
            "g4_oracle_passed": 3,
            "g4_oracle_total": 5,
            "g4_pass": False,
        }
        with caplog.at_level("INFO", logger=S.logger.name):
            with pytest.raises(S._TaskRejected) as exc:
                self._call_gate(monkeypatch, result)
        assert exc.value.reason.startswith("docker_gauntlet_kwok_oracle_pass_too_low")
        assert "0.60" in exc.value.reason
        assert any("oracle_reward=0.60" in r.getMessage() for r in caplog.records)

    def test_rejects_when_both_runs_collected_zero_tests(self, monkeypatch) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.0,
            "g3_empty_passed": 0,
            "g3_empty_total": 0,
            "g3_pass": True,
            "g4_oracle_pass_rate": 0.0,
            "g4_oracle_passed": 0,
            "g4_oracle_total": 0,
            "g4_pass": False,
        }
        with pytest.raises(S._TaskRejected) as exc:
            self._call_gate(monkeypatch, result)
        assert exc.value.reason == "docker_gauntlet_kwok_startup_failed"

    def test_docker_unavailable_is_passthrough(self, monkeypatch) -> None:
        result = {"skipped": True, "reason": "docker_unavailable"}
        out = self._call_gate(monkeypatch, result)
        assert out is result

    def test_forwards_kwok_backend_and_timeout_to_runner(self, monkeypatch) -> None:
        captured: dict = {}

        def fake(**kw):
            captured.update(kw)
            return {
                "skipped": False,
                "image_tag": "img",
                "g3_empty_pass_rate": 0.0,
                "g3_empty_passed": 0,
                "g3_empty_total": 3,
                "g3_pass": True,
                "g4_oracle_pass_rate": 1.0,
                "g4_oracle_passed": 3,
                "g4_oracle_total": 3,
                "g4_pass": True,
            }

        monkeypatch.setattr(S, "_run_docker_gauntlet_g3g4", fake)
        opts = _kwok_opts()
        S._run_g3g4_gauntlet_gate(
            options=opts,
            dockerfile="FROM scratch\n",
            aux_files={"tests/conftest.py": ""},
            test_script="",
            oracle_code="",
            task_id="tid",
        )
        assert captured["backend"] == "kwok"
        assert captured["timeout_sec"] == 480
        assert captured["empty_max"] == 0.05
        assert captured["oracle_min"] == 1.0


class TestGauntletGateAwsPathUnchanged:
    def test_minio_backend_keeps_legacy_reject_reason_for_g3(self, monkeypatch) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.5,
            "g3_empty_passed": 2,
            "g3_empty_total": 4,
            "g3_pass": False,
            "g4_oracle_pass_rate": 1.0,
            "g4_oracle_passed": 4,
            "g4_oracle_total": 4,
            "g4_pass": True,
        }
        monkeypatch.setattr(S, "_run_docker_gauntlet_g3g4", lambda **kw: result)
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="minio")
        with pytest.raises(S._TaskRejected) as exc:
            S._run_g3g4_gauntlet_gate(
                options=opts,
                dockerfile="",
                aux_files={},
                test_script="",
                oracle_code="",
            )
        assert exc.value.reason.startswith("gauntlet_g3_non_discriminative_")
        assert "kwok" not in exc.value.reason

    def test_minio_backend_keeps_legacy_reject_reason_for_g4(self, monkeypatch) -> None:
        result = {
            "skipped": False,
            "image_tag": "img",
            "g3_empty_pass_rate": 0.0,
            "g3_empty_passed": 0,
            "g3_empty_total": 4,
            "g3_pass": True,
            "g4_oracle_pass_rate": 0.5,
            "g4_oracle_passed": 2,
            "g4_oracle_total": 4,
            "g4_pass": False,
        }
        monkeypatch.setattr(S, "_run_docker_gauntlet_g3g4", lambda **kw: result)
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="minio")
        with pytest.raises(S._TaskRejected) as exc:
            S._run_g3g4_gauntlet_gate(
                options=opts,
                dockerfile="",
                aux_files={},
                test_script="",
                oracle_code="",
            )
        assert exc.value.reason.startswith("gauntlet_g4_oracle_failing_")
        assert "kwok" not in exc.value.reason
