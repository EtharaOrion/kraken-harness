"""LLM provider failover: 5xx / rate-limit / timeout → spec.fallback retry."""

from __future__ import annotations

from unittest import mock

import pytest

from repo2rlenv.llm import LLMResponse, _do_complete, _is_failover_eligible, complete
from repo2rlenv.spec.input import LLMSpec

# ----------------------------------------------------------------------------
# _is_failover_eligible — exception classification
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc_class_name,expected",
    [
        ("InternalServerError", True),  # 5xx including Anthropic 529
        ("RateLimitError", True),
        ("ServiceUnavailableError", True),
        ("APIConnectionError", True),
        ("Timeout", True),
        ("APIError", True),
        ("BadRequestError", False),  # 400 — config bug, don't retry
        ("AuthenticationError", False),  # 401
        ("NotFoundError", False),  # 404 — wrong model
        ("ValueError", False),  # not provider-related at all
    ],
)
def test_failover_eligibility(exc_class_name, expected):
    # Build a synthetic exception with the right class name
    exc = type(exc_class_name, (Exception,), {})("test")
    assert _is_failover_eligible(exc) is expected


# ----------------------------------------------------------------------------
# complete() — fallback behavior
# ----------------------------------------------------------------------------


def _ok_response(content="hello") -> LLMResponse:
    return LLMResponse(content=content, cost_usd=0.001, prompt_tokens=5, completion_tokens=1)


def test_no_fallback_succeeds_first_try():
    spec = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")
    with mock.patch("repo2rlenv.llm._do_complete", return_value=_ok_response("hi")) as m:
        r = complete(spec, user="prompt")
    assert r.content == "hi"
    assert m.call_count == 1


def test_fallback_fires_on_retryable_error():
    primary = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")
    fallback = LLMSpec(provider="openai", model="gpt-5.5")
    primary = primary.model_copy(update={"fallback": fallback})

    overloaded = type("InternalServerError", (Exception,), {})("Overloaded 529")
    calls = []

    def fake_do_complete(spec, **kwargs):
        calls.append(spec.qualified_name)
        if spec.qualified_name == "anthropic/claude-sonnet-4-6":
            raise overloaded
        return _ok_response("from-fallback")

    with mock.patch("repo2rlenv.llm._do_complete", side_effect=fake_do_complete):
        r = complete(primary, user="prompt")

    assert r.content == "from-fallback"
    assert calls == ["anthropic/claude-sonnet-4-6", "openai/gpt-5.5"]


def test_fallback_does_not_fire_on_bad_request():
    """4xx errors signal config bugs (wrong model id, bad params) — re-raise."""
    primary = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")
    fallback = LLMSpec(provider="openai", model="gpt-5.5")
    primary = primary.model_copy(update={"fallback": fallback})

    bad = type("BadRequestError", (Exception,), {})("unknown model")

    with mock.patch("repo2rlenv.llm._do_complete", side_effect=bad):
        with pytest.raises(Exception, match="unknown model"):
            complete(primary, user="prompt")


def test_no_fallback_set_reraises():
    """If spec.fallback is None, retryable errors still propagate."""
    spec = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")  # no fallback
    overloaded = type("InternalServerError", (Exception,), {})("Overloaded")

    with mock.patch("repo2rlenv.llm._do_complete", side_effect=overloaded):
        with pytest.raises(Exception, match="Overloaded"):
            complete(spec, user="prompt")


# ----------------------------------------------------------------------------
# _do_complete — Bedrock env-auth path (no api_key required / passed)
# ----------------------------------------------------------------------------


def _fake_litellm_response(content="ok"):
    msg = type("Msg", (), {"content": content})()
    choice = type("Choice", (), {"message": msg})()
    return type("Resp", (), {"choices": [choice], "usage": None})()


def test_do_complete_bedrock_no_key_no_api_key_passed(monkeypatch):
    """Bedrock must not hard-fail without an api_key, and must not pass one to
    litellm — AWS creds are resolved from the environment. Opus-4-7 ARN also
    drops `temperature`."""
    import litellm  # type: ignore[import-untyped]

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_litellm_response("from-bedrock")

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **k: 0.0)
    # No bearer token, no AWS creds set — must still proceed (litellm's job).
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    arn = "arn:aws:bedrock:us-east-1:123:inference-profile/us.anthropic.claude-opus-4-7-x"
    spec = LLMSpec(provider="bedrock", model=arn)
    resp = _do_complete(spec, system=None, user="hi", max_tokens=16, temperature=0.5)

    assert resp.content == "from-bedrock"
    assert "api_key" not in captured  # env-auth: never passed
    assert captured["model"] == f"bedrock/{arn}"
    assert captured.get("drop_params") is True
    assert "temperature" not in captured  # opus-4-7 ARN → temperature dropped


def test_do_complete_anthropic_still_requires_key(monkeypatch):
    """Non-env-auth providers still hard-fail with no key (unchanged behavior)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = LLMSpec(provider="anthropic", model="claude-sonnet-4-6")
    with pytest.raises(RuntimeError, match="no API key resolved"):
        _do_complete(spec, system=None, user="hi", max_tokens=16, temperature=0.5)


def test_do_complete_retries_without_temperature_on_rejection(monkeypatch):
    """Opaque ARN can't be pre-detected, so temperature is sent and the model
    rejects it. We must strip `temperature`, retry once, succeed, and remember
    the model so the next call skips temperature entirely (budget-friendly)."""
    import litellm  # type: ignore[import-untyped]

    from repo2rlenv import llm as llm_mod

    arn = "arn:aws:bedrock:ap-south-1:1:application-inference-profile/opaque123"
    llm_mod._RUNTIME_NO_TEMPERATURE.discard(arn)  # clean slate

    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(dict(kwargs))
        if "temperature" in kwargs:
            raise type("BadRequestError", (Exception,), {})(
                "BedrockException - `temperature` is deprecated for this model."
            )
        return _fake_litellm_response("ok-after-retry")

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **k: 0.0)

    spec = LLMSpec(provider="bedrock", model=arn)
    resp = _do_complete(spec, system=None, user="hi", max_tokens=16, temperature=0.5)

    assert resp.content == "ok-after-retry"
    assert len(calls) == 2  # first with temperature (rejected), retry without
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]
    assert arn in llm_mod._RUNTIME_NO_TEMPERATURE  # remembered for the run

    # Second invocation must NOT send temperature at all → single call.
    calls.clear()
    resp2 = _do_complete(spec, system=None, user="hi", max_tokens=16, temperature=0.5)
    assert resp2.content == "ok-after-retry"
    assert len(calls) == 1
    assert "temperature" not in calls[0]
    llm_mod._RUNTIME_NO_TEMPERATURE.discard(arn)  # don't leak into other tests


# ----------------------------------------------------------------------------
# _resolve_cost_usd — native pricing / env fallback / loud warning
# ----------------------------------------------------------------------------


def test_cost_uses_native_litellm_when_available(monkeypatch):
    import litellm  # type: ignore[import-untyped]

    from repo2rlenv.llm import _resolve_cost_usd

    monkeypatch.setattr(litellm, "completion_cost", lambda **k: 0.001234)
    # Env rates set, but native pricing must take precedence.
    monkeypatch.setenv("R2E_COST_INPUT_PER_1M", "5")
    monkeypatch.setenv("R2E_COST_OUTPUT_PER_1M", "25")

    cost = _resolve_cost_usd("anthropic/claude-sonnet-4-6", object(), 100, 50)
    assert cost == 0.001234


def test_cost_falls_back_to_env_rates_when_unmapped(monkeypatch):
    """Opaque ARN: completion_cost raises → compute from env per-1M rates."""
    import litellm  # type: ignore[import-untyped]

    from repo2rlenv.llm import _resolve_cost_usd

    def boom(**k):
        raise Exception("This model isn't mapped yet")

    monkeypatch.setattr(litellm, "completion_cost", boom)
    monkeypatch.setenv("R2E_COST_INPUT_PER_1M", "5")  # $5 / 1M in
    monkeypatch.setenv("R2E_COST_OUTPUT_PER_1M", "25")  # $25 / 1M out

    # 34 in / 7 out at 5/25 per 1M = 34*5e-6 + 7*25e-6 = 0.00017 + 0.000175
    cost = _resolve_cost_usd("bedrock/converse/arn:...:opaque", object(), 34, 7)
    assert cost == pytest.approx(0.000345)


def test_cost_warns_once_when_unpriced(monkeypatch, caplog):
    """No native price, no env rates → return 0.0 and warn loudly (once)."""
    import logging

    import litellm  # type: ignore[import-untyped]

    from repo2rlenv import llm as llm_mod

    def boom(**k):
        raise Exception("This model isn't mapped yet")

    monkeypatch.setattr(litellm, "completion_cost", boom)
    monkeypatch.delenv("R2E_COST_INPUT_PER_1M", raising=False)
    monkeypatch.delenv("R2E_COST_OUTPUT_PER_1M", raising=False)
    model = "bedrock/converse/arn:...:unpriced-test"
    llm_mod._WARNED_UNPRICED.discard(model)

    with caplog.at_level(logging.WARNING):
        c1 = llm_mod._resolve_cost_usd(model, object(), 10, 5)
        c2 = llm_mod._resolve_cost_usd(model, object(), 10, 5)

    assert c1 == 0.0 and c2 == 0.0
    warnings = [r for r in caplog.records if "max_llm_spend_usd" in r.getMessage()]
    assert len(warnings) == 1  # warned exactly once, not per call
    llm_mod._WARNED_UNPRICED.discard(model)


def test_fallback_chain_caps_recursion():
    """Three nested fallbacks all failing → still re-raises (no infinite loop)."""
    layer3 = LLMSpec(provider="huggingface", model="qwen")
    layer2 = LLMSpec(provider="openai", model="gpt-5.5").model_copy(update={"fallback": layer3})
    layer1 = LLMSpec(provider="anthropic", model="claude-sonnet-4-6").model_copy(
        update={"fallback": layer2}
    )
    # Even self-referential to force depth: layer3.fallback = layer1 (would loop)
    layer3_loop = layer3.model_copy(update={"fallback": layer1})
    layer2 = layer2.model_copy(update={"fallback": layer3_loop})
    layer1 = layer1.model_copy(update={"fallback": layer2})

    overloaded = type("InternalServerError", (Exception,), {})("Overloaded")
    calls = []

    def fake_do_complete(spec, **kwargs):
        calls.append(spec.qualified_name)
        raise overloaded

    with mock.patch("repo2rlenv.llm._do_complete", side_effect=fake_do_complete):
        with pytest.raises(Exception, match="Overloaded"):
            complete(layer1, user="prompt")

    # Should attempt primary + at most 3 fallbacks → 4 total
    assert len(calls) <= 4
