#!/usr/bin/env python3
"""Query the self-hosted Helicone API and dump raw JSON responses.

Two modes:
  1. --query-only : skip the LLM call, just query Helicone for existing logs
  2. (default)   : make a cheap LLM call first, then query Helicone

Usage:
    python scripts/test_helicone.py --query-only
    TEST_MODEL=bedrock/converse/... python scripts/test_helicone.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

HELICONE_BASE = os.environ.get("HELICONE_API_BASE", "https://api.helicone.ai")
HELICONE_KEY = os.environ.get("HELICONE_API_KEY", "")
QUERY_ONLY = "--query-only" in sys.argv

print(f"Helicone base : {HELICONE_BASE}")
print(f"Helicone key  : {HELICONE_KEY[:12]}...")
print(f"Mode          : {'query-only' if QUERY_ONLY else 'call + query'}")
print()


def try_request(method: str, url: str, body: bytes | None = None) -> dict | None:
    headers = {"Authorization": f"Bearer {HELICONE_KEY}"}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            print(f"  {method} {url}")
            print(f"  Status: {resp.status}")
            print(f"  Headers: {dict(resp.headers)}")
            print()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                print(f"  (non-JSON body, length={len(raw)})")
                print(f"  {raw[:2000]}")
                return None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"  {method} {url}  ->  HTTP {e.code}")
        if body_text:
            print(f"  Body: {body_text[:1000]}")
        print()
        return None
    except Exception as e:
        print(f"  {method} {url}  ->  {type(e).__name__}: {e}")
        print()
        return None


# ---- Step 1: make LLM call (optional) ----
if not QUERY_ONLY:
    try:
        import litellm
        from litellm import completion
        from swefficiency.observability import helicone_metadata, setup_helicone

        ok = setup_helicone()
        if not ok:
            print("WARN: Helicone setup returned False (key missing?)")

        MODEL = os.environ.get(
            "TEST_MODEL", "bedrock/converse/global.anthropic.claude-opus-4-6-v1"
        )
        meta = helicone_metadata(
            call_type="test",
            model_id=MODEL.split("/")[-1],
            session_id="test-helicone-smoke",
            session_name="Helicone Smoke Test",
            extra={"Script": "test_helicone.py"},
        )
        print(f"Calling: {MODEL}")
        print(f"Metadata: {json.dumps(meta, indent=2)}")
        print()

        resp = completion(
            model=MODEL,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=10,
            metadata=meta,
        )
        print("=== LLM RESPONSE ===")
        print(resp.choices[0].message.content)
        print()
        print("=== FULL LITELLM RESPONSE ===")
        print(json.dumps(resp.model_dump(), indent=2, default=str))
        print()
        print("Waiting 5s for Helicone to ingest...")
        time.sleep(5)

    except Exception as e:
        print(f"LLM call failed: {e}")
        print("Continuing to Helicone API query anyway...")
        print()

# ---- Step 2: probe Helicone API endpoints ----
print("=" * 60)
print("PROBING HELICONE API")
print("=" * 60)
print()

post_query = json.dumps(
    {
        "filter": "all",
        "offset": 0,
        "limit": 3,
        "sort": {"created_at": "desc"},
    }
).encode()

post_query_v2 = json.dumps(
    {
        "filter": {},
        "limit": 3,
        "sort": {"created_at": "desc"},
    }
).encode()

endpoints = [
    ("POST", "/v1/request/query", post_query),
    ("POST", "/api/request/query", post_query),
    ("POST", "/v1/request/query", post_query_v2),
    ("GET", "/v1/request?limit=3", None),
    ("GET", "/api/request?limit=3", None),
    ("GET", "/v1/requests?limit=3", None),
    ("GET", "/api/requests?limit=3", None),
    ("GET", "/v1/health", None),
    ("GET", "/api/health", None),
    ("GET", "/health", None),
    ("GET", "/", None),
]

found = False
for method, path, body in endpoints:
    url = f"{HELICONE_BASE}{path}"
    data = try_request(method, url, body)
    if data is not None:
        print("=== RAW HELICONE JSON ===")
        print(json.dumps(data, indent=2, default=str))
        print()
        found = True
        break

if not found:
    print("No successful endpoint found.")
    print()
    print("Trying raw GET to base URL for discovery...")
    try_request("GET", HELICONE_BASE, None)
    print()
    print(f"Check the Helicone web dashboard at: {HELICONE_BASE}")
