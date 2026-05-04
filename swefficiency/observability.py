"""Helicone AI observability integration for litellm.

Configures litellm to report all LLM calls to Helicone via the native
callback mechanism.  Call ``setup_helicone()`` once at process startup
(or use ``setup_helicone_for_pool`` as a multiprocessing.Pool initializer)
before any ``litellm.completion()`` calls.

Environment variables (from ``.env`` or shell):
    HELICONE_API_KEY   - required for logging
    HELICONE_API_BASE  - self-hosted gateway (default: https://api.helicone.ai)
    HELICONE_USER      - optional user identifier
"""

from __future__ import annotations

import os
from pathlib import Path

import litellm
from dotenv import load_dotenv


_HELICONE_CONFIGURED = False

# Best-effort .env discovery: project root is two levels above this file
# (swefficiency/observability.py → repo root).
_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def setup_helicone() -> bool:
    """Activate the Helicone callback on ``litellm`` if credentials are set.

    Automatically calls ``load_dotenv()`` so standalone scripts that don't
    load ``.env`` themselves still pick up Helicone credentials.

    Helicone is only activated when the ``ENABLE_HELICONE`` environment
    variable is set (e.g. via ``--use-helicone`` in *run_pipeline.sh*).

    Safe to call multiple times; the callback is registered at most once
    per process.

    Returns ``True`` if Helicone was enabled, ``False`` if the API key is
    missing and logging was skipped.
    """
    global _HELICONE_CONFIGURED
    if _HELICONE_CONFIGURED:
        return True

    if _DOTENV_PATH.is_file():
        load_dotenv(_DOTENV_PATH, override=False)

    # Only activate if explicitly enabled
    if not os.environ.get("ENABLE_HELICONE"):
        return False

    api_key = os.environ.get("HELICONE_API_KEY")
    if not api_key:
        return False

    if "helicone" not in litellm.success_callback:
        litellm.success_callback.append("helicone")

    _HELICONE_CONFIGURED = True
    return True


def setup_helicone_for_pool() -> None:
    """``multiprocessing.Pool`` initializer that activates Helicone.

    Usage::

        with multiprocessing.Pool(processes=8, initializer=setup_helicone_for_pool):
            ...
    """
    setup_helicone()


def helicone_metadata(
    *,
    call_type: str,
    model_id: str | None = None,
    session_id: str | None = None,
    session_name: str | None = None,
    session_path: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Build the ``metadata`` dict for a ``litellm.completion()`` call.

    Parameters
    ----------
    call_type:
        Logical category of the call (e.g. ``"synthetic"``, ``"analysis"``).
    model_id:
        Human-readable model identifier (e.g. ``"opus-4.6"``).
    session_id:
        Optional Helicone session ID for grouping related calls.
    session_name:
        Optional human-readable session name.
    session_path:
        Optional hierarchical session path (e.g. ``"/pipeline/stage7"``).
    extra:
        Arbitrary extra Helicone properties (keys are automatically
        prefixed with ``Helicone-Property-``).
    """
    user = os.environ.get("HELICONE_USER", "")

    meta: dict = {
        "Helicone-Property-CallType": call_type,
    }

    if model_id:
        meta["Helicone-Property-ModelId"] = model_id

    if user:
        meta["Helicone-User-Id"] = user

    if session_id:
        meta["Helicone-Session-Id"] = session_id
    if session_name:
        meta["Helicone-Session-Name"] = session_name
    if session_path:
        meta["Helicone-Session-Path"] = session_path

    if extra:
        for k, v in extra.items():
            meta[f"Helicone-Property-{k}"] = v

    return meta


# ── Cost Tracking ───────────────────────────────────────────────

# Manual pricing table for Bedrock models where litellm returns $0.
# Prices are USD per 1M tokens.
BEDROCK_PRICING: dict[str, dict[str, float]] = {
    # Claude Opus 4.7 (dataset creation model)
    "global.anthropic.claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "anthropic.claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "us.anthropic.claude-opus-4-7": {"input": 5.50, "output": 27.50},
    # Claude Opus 4.6
    "global.anthropic.claude-opus-4-6-v1": {"input": 5.00, "output": 25.00},
    "us.anthropic.claude-opus-4-6-v1": {"input": 5.50, "output": 27.50},
    # Claude Sonnet 4
    "global.anthropic.claude-sonnet-4-v1": {"input": 3.00, "output": 15.00},
    "us.anthropic.claude-sonnet-4-v1": {"input": 3.30, "output": 16.50},
    "global.anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.00, "output": 15.00},
    # Amazon Nova
    "amazon.nova-lite-v1:0": {"input": 0.06, "output": 0.24},
    "amazon.nova-pro-v1:0": {"input": 0.80, "output": 3.20},
    # GLM-5
    "zai.glm-5": {"input": 1.00, "output": 3.20},
}

_MODEL_ALIASES: dict[str, str] = {
    # Opus 4.7
    "bedrock/converse/global.anthropic.claude-opus-4-7": "global.anthropic.claude-opus-4-7",
    "bedrock/global.anthropic.claude-opus-4-7": "global.anthropic.claude-opus-4-7",
    # Opus 4.6
    "bedrock/converse/global.anthropic.claude-opus-4-6-v1": "global.anthropic.claude-opus-4-6-v1",
    "bedrock/global.anthropic.claude-opus-4-6-v1": "global.anthropic.claude-opus-4-6-v1",
    "bedrock/converse/us.anthropic.claude-opus-4-6-v1": "us.anthropic.claude-opus-4-6-v1",
    # Nova / GLM
    "bedrock/converse/amazon.nova-lite-v1:0": "amazon.nova-lite-v1:0",
    "bedrock/converse/amazon.nova-2-lite-v1:0": "amazon.nova-lite-v1:0",
    "bedrock/converse/zai.glm-5": "zai.glm-5",
    # ARN inference profiles (response model is raw ARN)
    "arn:aws:bedrock:us-east-1:426628337772:application-inference-profile/4w7tmk1iplxi": "global.anthropic.claude-opus-4-6-v1",
    "arn:aws:bedrock:us-east-1:426628337772:application-inference-profile/8lzlkxguk85a": "zai.glm-5",
    "arn:aws:bedrock:us-east-1:426628337772:application-inference-profile/a0q672msxd5z": "amazon.nova-lite-v1:0",
}


def _resolve_pricing_key(model: str) -> str | None:
    """Resolve a model string to a BEDROCK_PRICING key."""
    if model in BEDROCK_PRICING:
        return model
    if model in _MODEL_ALIASES:
        return _MODEL_ALIASES[model]
    stripped = model
    for prefix in ("bedrock/converse/", "bedrock/"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            if stripped in BEDROCK_PRICING:
                return stripped
    return None


def safe_completion_cost(
    response=None,
    *,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> float:
    """Compute USD cost, falling back to manual pricing if litellm returns 0.

    Can be called with a litellm response object OR with explicit token counts.
    """
    cost = 0.0
    if response is not None:
        try:
            from litellm import completion_cost
            cost = completion_cost(completion_response=response)
        except Exception:
            pass

    if cost > 0:
        return cost

    if response is not None:
        model = model or getattr(response, "model", None) or ""
        usage = getattr(response, "usage", None)
        if usage:
            prompt_tokens = prompt_tokens or getattr(usage, "prompt_tokens", 0)
            completion_tokens = completion_tokens or getattr(usage, "completion_tokens", 0)

    if not model:
        return 0.0

    key = _resolve_pricing_key(model)
    if key is None:
        return 0.0

    prices = BEDROCK_PRICING[key]
    return (prompt_tokens * prices["input"] + completion_tokens * prices["output"]) / 1_000_000
