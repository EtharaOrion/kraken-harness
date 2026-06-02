"""Live Bedrock smoke test — env-gated, makes ONE real call to AWS.

This is the *acceptance* test for Bedrock support. The mocked tests in
test_llm_fallback.py only prove we build the right kwargs; they never touch
AWS. This one actually hits Bedrock, so it's the only test that can confirm
an inference-profile ARN routes correctly, that Opus 4.7 accepts our request
(temperature handling), and what cost tracking reports.

Skipped by default. To run:

    set -a && source .env && set +a            # loads AWS creds + R2E_LLM
    R2E_LIVE_BEDROCK=1 uv run pytest tests/test_llm_bedrock_live.py -v -s
"""

from __future__ import annotations

import os

import pytest

from repo2rlenv.llm import complete
from repo2rlenv.spec.input import LLMSpec

_GATE = os.environ.get("R2E_LIVE_BEDROCK") == "1"


def _model_string() -> str:
    # Reuse the same full "bedrock/<model-or-ARN>" string the user keeps in
    # .env as R2E_LLM (the value passed to --llm). Falls back to a plain id.
    return os.environ.get("R2E_LLM") or os.environ.get("BEDROCK_MODEL_ID") or ""


@pytest.mark.skipif(
    not _GATE,
    reason="set R2E_LIVE_BEDROCK=1 (plus AWS creds + R2E_LLM) to run a real Bedrock call",
)
def test_bedrock_live_single_call():
    model = _model_string()
    assert model.startswith("bedrock/"), (
        f"R2E_LLM must look like 'bedrock/<model-or-ARN>'; got {model!r}. "
        "Set it in .env, e.g. R2E_LLM='bedrock/arn:aws:bedrock:...:inference-profile/...'"
    )

    # Mirror cli.py's parsing: split on the first '/' only so the ARN survives.
    provider, model_id = model.split("/", 1)
    spec = LLMSpec(provider=provider, model=model_id)

    resp = complete(
        spec,
        system="You are a terse assistant.",
        user="Reply with exactly one word: PONG",
        max_tokens=16,
        temperature=0.0,
    )

    # The real assertion: a non-empty response actually came back from Bedrock.
    assert resp.content.strip(), "empty response from Bedrock"

    # Surface the things the critique flagged so a human can eyeball them.
    print(f"\n[bedrock-live] model       = {spec.qualified_name}")
    print(f"[bedrock-live] reply       = {resp.content.strip()!r}")
    print(f"[bedrock-live] tokens in/out = {resp.prompt_tokens}/{resp.completion_tokens}")
    print(
        f"[bedrock-live] cost_usd    = {resp.cost_usd}  (0.0 ⇒ budget cap is inert for this model)"
    )
