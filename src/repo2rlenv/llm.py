"""LiteLLM wrapper — single entry point across providers, with cost tracking.

The pipelines call `complete(input, prompt)`; we resolve the API key from
either the LLMSpec hint or the provider-default env var, dispatch, then use
LiteLLM's `completion_cost()` to attach a USD estimate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from repo2rlenv.auth import resolve_llm_api_key

# from repo2rlenv.compression import maybe_compress
from repo2rlenv.spec.input import LLMSpec

logger = logging.getLogger(__name__)


# Models that reject any `temperature` value (forced default). Add patterns
# as new releases land. Probed empirically via scripts/probe_llm_routes.py.
_NO_TEMPERATURE_RE = re.compile(
    r"(claude-opus-4-7|claude-opus-4-8|gpt-5(\.|-|$)|gpt-6|o1-|o3-|o4-)",
    re.IGNORECASE,
)


# Models proven at runtime to reject `temperature` — populated when a call
# fails with a "temperature is deprecated/unsupported" error. Needed because
# opaque Bedrock inference-profile ARNs (e.g. application-inference-profile/<id>)
# carry no model name, so the regex above can't recognize Opus 4.7, and
# litellm's drop_params has no metadata to drop it either. After the first
# rejection we remember the model and stop sending temperature — so a long
# bootstrap loop pays the wasted call at most once, not every iteration.
_RUNTIME_NO_TEMPERATURE: set[str] = set()

# Matches Bedrock/OpenAI-style messages telling us `temperature` isn't allowed.
_TEMP_REJECTION_RE = re.compile(
    r"temperature.{0,40}(deprecat|unsupported|not support|isn't support|"
    r"is not support|may not|invalid|cannot be|must be)",
    re.IGNORECASE,
)


def _supports_temperature(model: str) -> bool:
    if model in _RUNTIME_NO_TEMPERATURE:
        return False
    return _NO_TEMPERATURE_RE.search(model) is None


def _is_temperature_rejection(exc: BaseException) -> bool:
    msg = str(exc)
    return "temperature" in msg.lower() and _TEMP_REJECTION_RE.search(msg) is not None


# Models we've already warned about being unpriced — warn once per process so
# the log isn't spammed across a long bootstrap loop.
_WARNED_UNPRICED: set[str] = set()


def _env_cost_rates() -> tuple[float | None, float | None]:
    """Per-token (input, output) USD rates from env, or (None, None).

    Lets the user supply pricing for models litellm can't map — notably opaque
    Bedrock application-inference-profile ARNs, where `completion_cost` raises
    "isn't mapped yet". Values are given per 1M tokens (the unit AWS/Anthropic
    publish) and converted to per-token here.
    """
    import os

    def _per_token(var: str) -> float | None:
        raw = os.environ.get(var)
        if not raw:
            return None
        try:
            return float(raw) / 1_000_000.0
        except ValueError:
            logger.warning("ignoring non-numeric %s=%r", var, raw)
            return None

    return _per_token("R2E_COST_INPUT_PER_1M"), _per_token("R2E_COST_OUTPUT_PER_1M")


def _resolve_cost_usd(
    model: str, response: object, prompt_tokens: int, completion_tokens: int
) -> float:
    """Best-effort USD cost for one call, with a configurable fallback.

    Order: (1) litellm's native model_cost table; (2) env-configured per-token
    rates (R2E_COST_INPUT_PER_1M / R2E_COST_OUTPUT_PER_1M) computed from the
    real token counts; (3) give up and WARN loudly — a 0.0 cost silently
    disables `max_llm_spend_usd`, so the user must know it's not being tracked.
    """
    import litellm  # type: ignore[import-untyped]

    try:
        native = float(litellm.completion_cost(completion_response=response))
        if native > 0:
            return native
    except Exception as exc:
        logger.debug("completion_cost failed for %s: %s", model, exc)

    in_rate, out_rate = _env_cost_rates()
    if in_rate is not None and out_rate is not None:
        return prompt_tokens * in_rate + completion_tokens * out_rate

    if model not in _WARNED_UNPRICED:
        _WARNED_UNPRICED.add(model)
        logger.warning(
            "cost tracking unavailable for %s (litellm can't price it — e.g. an "
            "opaque Bedrock ARN). cost_usd=0.0, so `max_llm_spend_usd` is INERT. "
            "Set R2E_COST_INPUT_PER_1M / R2E_COST_OUTPUT_PER_1M to enable it, and "
            "rely on max_iterations / max_seconds as your spend guard.",
            model,
        )
    return 0.0


# Providers whose credentials are resolved by the underlying SDK from the
# environment, NOT via a simple `api_key` string. For these we must NOT
# hard-fail when `resolve_llm_api_key` returns None, and must NOT pass
# `api_key=` into litellm — it reads the provider's env vars itself.
#   - bedrock: AWS_BEARER_TOKEN_BEDROCK  *or*  AWS_ACCESS_KEY_ID/SECRET/REGION
# Only bedrock is listed because it's the only one tested end-to-end. Add
# vertex_ai / azure here when they're actually verified — not speculatively.
ENV_AUTH_PROVIDERS = {"bedrock", "vertex_ai"}


@dataclass(slots=True)
class LLMResponse:
    content: str
    usage: dict | None = None
    cost_usd: float = 0.0  # cost of THIS call, in USD (best-effort)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None


def _is_failover_eligible(exc: BaseException) -> bool:
    """True for transient provider errors worth retrying on a fallback model.

    LiteLLM raises specific subclasses; we match on class names so we don't
    have to import the symbols (some live in nested submodules and shift
    between versions).
    """
    name = type(exc).__name__
    # Retry on: 5xx upstream, rate limits, network blips, timeouts.
    # Don't retry on: 4xx bad-request, auth errors, not-found, content filter.
    return name in {
        "InternalServerError",  # 5xx incl. Anthropic 529 Overloaded
        "RateLimitError",  # 429
        "ServiceUnavailableError",
        "APIConnectionError",
        "Timeout",
        "APIError",  # generic upstream error
    }


def _do_complete(
    spec: LLMSpec,
    *,
    system: str | None,
    user: str,
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    """One non-fallback chat-completion call. Internal helper for `complete()`."""
    import litellm  # type: ignore[import-untyped]

    provider = spec.provider.lower()
    api_key = resolve_llm_api_key(spec.provider, spec.api_key_env)
    if api_key is None and provider not in ENV_AUTH_PROVIDERS:
        raise RuntimeError(
            f"no API key resolved for provider {spec.provider!r}. "
            f"Set {spec.api_key_env or 'the provider-default env var'}."
        )

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    # messages = maybe_compress(messages, spec.qualified_name)

    kwargs: dict = {
        "model": spec.qualified_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": spec.timeout_sec,
        # Ask litellm to drop params a model is *known* to reject. NB: this only
        # works when litellm has metadata for the model — it does NOT help for
        # opaque Bedrock ARNs (no model name → no metadata). The real backstop
        # for that case is the temperature-rejection retry below.
        "drop_params": True,
    }
    # Env-auth providers (Bedrock) resolve creds from the environment inside
    # litellm; passing api_key= is wrong/ignored for them.
    if api_key is not None and provider not in ENV_AUTH_PROVIDERS:
        kwargs["api_key"] = api_key
    # Newer reasoning-focused models (Opus 4.7+, GPT-5+) reject `temperature`.
    if _supports_temperature(spec.model):
        kwargs["temperature"] = temperature
    if spec.endpoint:
        kwargs["api_base"] = spec.endpoint

    if spec.provider == "huggingface" and spec.endpoint is None:
        kwargs.setdefault("api_base", "https://router.huggingface.co/v1")

    try:
        response = litellm.completion(**kwargs)
    except Exception as exc:
        # The model rejected `temperature` (common for Opus 4.7+/reasoning models
        # behind opaque Bedrock ARNs we can't pre-detect). Remember the model so
        # future calls skip the param, strip it, and retry this call once.
        if "temperature" in kwargs and _is_temperature_rejection(exc):
            logger.info(
                "%s rejected `temperature`; retrying without it (remembered for this run)",
                spec.qualified_name,
            )
            _RUNTIME_NO_TEMPERATURE.add(spec.model)
            kwargs.pop("temperature", None)
            response = litellm.completion(**kwargs)
        else:
            raise
    choice = response.choices[0]
    content = choice.message.content or ""
    finish_reason = getattr(choice, "finish_reason", None)

    usage_obj = getattr(response, "usage", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage_obj is not None:
        prompt_tokens = getattr(usage_obj, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage_obj, "completion_tokens", 0) or 0

    cost_usd = _resolve_cost_usd(spec.qualified_name, response, prompt_tokens, completion_tokens)

    return LLMResponse(
        content=content,
        usage=dict(usage_obj) if usage_obj else None,
        cost_usd=cost_usd,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        finish_reason=finish_reason,
    )


def complete(
    spec: LLMSpec,
    *,
    system: str | None = None,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    _depth: int = 0,
) -> LLMResponse:
    """Single chat-completion call with automatic fallback on transient errors.

    Calls `spec.qualified_name`. On 5xx / 429 / network / timeout errors, if
    `spec.fallback` is set, retries with the fallback model recursively (up
    to 3 levels deep, then re-raises). 4xx errors (bad model, auth, etc.)
    are NOT retried — those signal config bugs, not transient failures.

    Honors `LLMSpec.endpoint` for self-hosted backends.
    """
    try:
        return _do_complete(
            spec,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        if _depth >= 3 or spec.fallback is None or not _is_failover_eligible(exc):
            raise
        logger.warning(
            "primary LLM %s failed with %s; falling back to %s",
            spec.qualified_name,
            type(exc).__name__,
            spec.fallback.qualified_name,
        )
        return complete(
            spec.fallback,
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
            _depth=_depth + 1,
        )
