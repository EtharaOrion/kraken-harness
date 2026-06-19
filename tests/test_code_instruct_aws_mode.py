from __future__ import annotations

from unittest.mock import patch

from repo2rlenv.pipelines._oss_instruct import PROMPT_SYSTEM, PROMPT_SYSTEM_AWS
from repo2rlenv.pipelines.code_instruct import (
    _AWS_CLI_VERSION,
    _AWS_CONFTEST_B64,
    _AWS_CONFTEST_BODY,
    _MOTO_UNAVAILABLE_SENTINEL,
    _aws_verify_preamble,
    _references_aws,
    build_aws_eval_script,
    build_code_instruct_dockerfile,
)
from repo2rlenv.spec.options import CodeInstructOptions


def test_options_default_aws_mode_false():
    assert CodeInstructOptions().aws_mode is False


def test_dockerfile_plain_mode_no_moto():
    dockerfile = build_code_instruct_dockerfile("python:3.12-slim")
    assert "moto" not in dockerfile
    assert "awscli" not in dockerfile
    assert "aws --version" not in dockerfile


def test_dockerfile_aws_mode_installs_moto():
    dockerfile = build_code_instruct_dockerfile("python:3.12-slim", aws_mode=True)
    assert "pip install" in dockerfile
    assert "moto[all,server]>=5.0" in dockerfile
    assert "boto3>=1.34" in dockerfile
    assert "awscli.amazonaws.com/awscli-exe-linux-" in dockerfile


def test_dockerfile_aws_mode_pins_v2():
    dockerfile = build_code_instruct_dockerfile("python:3.12-slim", aws_mode=True)
    assert "RUN aws --version" in dockerfile


def test_dockerfile_aws_mode_pins_cli_version():
    dockerfile = build_code_instruct_dockerfile("python:3.12-slim", aws_mode=True)
    assert _AWS_CLI_VERSION in dockerfile
    assert f"-{_AWS_CLI_VERSION}.zip" in dockerfile
    assert "awscli-exe-linux-latest" not in dockerfile


def test_dockerfile_aws_mode_supports_multiple_arches():
    dockerfile = build_code_instruct_dockerfile("python:3.12-slim", aws_mode=True)
    assert "x86_64|amd64) cli_arch=x86_64" in dockerfile
    assert "aarch64|arm64) cli_arch=aarch64" in dockerfile
    assert "unsupported arch" in dockerfile


def test_eval_script_aws_mode_starts_moto():
    script = build_aws_eval_script(
        ["python -m pytest test_thing.py -v --no-header"],
        language="python",
    )
    assert 'moto_server -H 127.0.0.1 -p "$MOTO_PORT"' in script
    assert '(echo > /dev/tcp/127.0.0.1/"$MOTO_PORT")' in script
    assert "trap 'kill $MOTO_PID 2>/dev/null || true' EXIT" in script
    assert "exit 99" in script


def test_eval_script_honors_moto_port_env():
    script = build_aws_eval_script(["pytest"], language="python")
    assert 'MOTO_PORT="${MOTO_PORT:-5000}"' in script
    assert 'export AWS_ENDPOINT_URL="http://127.0.0.1:${MOTO_PORT}"' in script


def test_eval_script_aws_mode_sets_env():
    script = build_aws_eval_script(["pytest"], language="python")
    assert 'export AWS_ENDPOINT_URL="http://127.0.0.1:${MOTO_PORT}"' in script
    assert "export AWS_ACCESS_KEY_ID=testing" in script
    assert "export AWS_SECRET_ACCESS_KEY=testing" in script
    assert "export AWS_DEFAULT_REGION=us-east-1" in script
    assert "export AWS_SESSION_TOKEN=testing" in script


def test_eval_script_aws_mode_resets_state():
    script = build_aws_eval_script(["pytest"], language="python")
    reset_idx = script.find('curl -sX POST "${AWS_ENDPOINT_URL}/moto-api/reset"')
    test_idx = script.find("( pytest )")
    assert reset_idx != -1
    assert test_idx != -1
    assert reset_idx < test_idx


def test_eval_script_aws_mode_writes_conftest():
    script = build_aws_eval_script(["pytest"], language="python")
    expected = f"echo {_AWS_CONFTEST_B64} | base64 -d > /workspace/conftest.py"
    assert expected in script
    conftest_idx = script.find(expected)
    test_idx = script.find("( pytest )")
    assert conftest_idx < test_idx


def test_aws_conftest_body_resets_moto_per_test():
    assert "@pytest.fixture(autouse=True)" in _AWS_CONFTEST_BODY
    assert "/moto-api/reset" in _AWS_CONFTEST_BODY
    assert 'method="POST"' in _AWS_CONFTEST_BODY


def test_aws_conftest_body_reports_reset_failures():
    assert "import sys" in _AWS_CONFTEST_BODY
    assert "r2e:moto-reset-failed" in _AWS_CONFTEST_BODY
    assert "file=sys.stderr" in _AWS_CONFTEST_BODY


def test_aws_prompt_warns_about_state_isolation_and_waiters():
    assert "isolated" in PROMPT_SYSTEM_AWS
    assert "get_waiter" in PROMPT_SYSTEM_AWS


def test_eval_script_includes_test_block():
    script = build_aws_eval_script(
        ["python -m pytest a.py", "python -m pytest b.py"],
        language="python",
    )
    assert "( python -m pytest a.py && python -m pytest b.py )" in script


def test_synthesis_prompt_picked_by_flag():
    from repo2rlenv.pipelines import code_instruct as mod

    captured = {}

    class _FakeResp:
        cost_usd = 0.0
        content = "[Problem Description]\nx\n[Test]\ny\n[Solution]\nz"

    def fake_complete(spec, *, system, user, **kwargs):
        captured["system"] = system
        return _FakeResp()

    class _Seed:
        relative_path = "x.py"
        start_line = 1
        end_line = 10
        text = "def f(): pass"

    class _LLM:
        qualified_name = "fake/model"

    class _Bootstrap:
        pass

    class _Input:
        llm = _LLM()

    class _Pipeline:
        def __init__(self, aws_mode):
            self.input = _Input()
            self._llm = _LLM()
            self.options = CodeInstructOptions(aws_mode=aws_mode)
            self.bootstrap = _Bootstrap()
            self._llm_cost_usd = 0.0

    pipe_off = _Pipeline(aws_mode=False)
    pipe_on = _Pipeline(aws_mode=True)

    with patch.object(mod, "complete", side_effect=fake_complete):
        mod.CodeInstructPipeline._llm_synthesize(pipe_off, _Seed())
        assert captured["system"] is PROMPT_SYSTEM

        mod.CodeInstructPipeline._llm_synthesize(pipe_on, _Seed())
        assert captured["system"] is PROMPT_SYSTEM_AWS


def test_references_aws_helper_accepts_boto3():
    assert _references_aws("import boto3\nclient = boto3.client('s3')", "")
    assert _references_aws("", "import boto3")


def test_references_aws_helper_accepts_aws_string_literal():
    assert _references_aws("x = 'aws'", "")
    assert _references_aws('x = "aws"', "")


def test_references_aws_helper_rejects_plain_python():
    assert not _references_aws(
        "def add(a, b): return a + b",
        "def add(a, b):\n    return a + b",
    )
    assert not _references_aws("import os", "import json")


def test_aws_verify_preamble_uses_port_specific_pgrep():
    preamble = _aws_verify_preamble()
    assert 'pgrep -f "moto_server -H 127.0.0.1 -p ${MOTO_PORT}"' in preamble


def test_aws_verify_preamble_sentinel_is_last_line_on_failure():
    preamble = _aws_verify_preamble()
    cat_idx = preamble.find("cat /tmp/moto.log >&2")
    sentinel_idx = preamble.find(_MOTO_UNAVAILABLE_SENTINEL)
    assert cat_idx != -1
    assert sentinel_idx != -1
    assert cat_idx < sentinel_idx


def test_aws_verify_preamble_honors_moto_port_env():
    preamble = _aws_verify_preamble()
    assert 'MOTO_PORT="${MOTO_PORT:-5000}"' in preamble
    assert 'export AWS_ENDPOINT_URL="http://127.0.0.1:${MOTO_PORT}"' in preamble


def test_aws_conftest_body_blocks_non_loopback_sockets():
    assert "_R2E_ORIG_CONNECT = socket.socket.connect" in _AWS_CONFTEST_BODY
    assert "socket.socket.connect = _r2e_guarded_connect" in _AWS_CONFTEST_BODY
    assert "r2e:network-isolation" in _AWS_CONFTEST_BODY


def test_aws_conftest_body_allows_loopback_only():
    assert "_r2e_is_loopback" in _AWS_CONFTEST_BODY
    assert "127." in _AWS_CONFTEST_BODY
    assert '"localhost"' in _AWS_CONFTEST_BODY
    assert '"::1"' in _AWS_CONFTEST_BODY


def test_aws_verify_preamble_disables_imds():
    assert "export AWS_EC2_METADATA_DISABLED=true" in _aws_verify_preamble()


def test_eval_script_aws_mode_disables_imds():
    script = build_aws_eval_script(["pytest"], language="python")
    assert "export AWS_EC2_METADATA_DISABLED=true" in script


def test_eval_script_aws_mode_writes_reward_file():
    script = build_aws_eval_script(["pytest"], language="python")
    assert "/logs/verifier/reward.txt" in script
    assert 'echo "1.0" > /logs/verifier/reward.txt' in script
    assert 'echo "0.0" > /logs/verifier/reward.txt' in script
