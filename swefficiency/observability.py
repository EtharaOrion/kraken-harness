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
