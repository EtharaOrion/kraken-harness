#!/usr/bin/env bash
#
# Detect + handshake the LLM proxy (e.g. a Claude-subscription bridge), then
# print the exact `llm:` config block to feed `repo2rlenv generate --config`.
# Read-only except for ONE tiny (~5-token) completion to confirm the round-trip.
# Run this the moment the proxy is up; it does NOT generate any tasks.
#
# Env:
#   PROXY_URL    default http://localhost:3456
#   PROXY_TOKEN  bearer / x-api-key value (leave empty for a no-auth local bridge)
#   MODEL        model name the proxy expects (auto-detected for OpenAI-style)
set -uo pipefail

URL="${PROXY_URL:-http://localhost:3456}"
TOK="${PROXY_TOKEN:-}"
MODEL="${MODEL:-}"
base="${URL%/}"

log()  { printf '\033[1m[proxy]\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m %s\n' "$*"; }
no()   { printf '  \033[31m--\033[0m %s\n' "$*"; }

# 1. reachable?
code="$(curl -s -m 4 -o /dev/null -w '%{http_code}' "$base/" 2>/dev/null || echo 000)"
if [ "$code" = "000" ]; then
  no "nothing answering at $base — start the proxy (or fix PROXY_URL) and re-run."
  exit 1
fi
ok "reachable at $base (root -> HTTP $code)"

auth_openai=(); [ -n "$TOK" ] && auth_openai=(-H "Authorization: Bearer $TOK")
auth_anthropic=(-H "anthropic-version: 2023-06-01"); [ -n "$TOK" ] && auth_anthropic+=(-H "x-api-key: $TOK")

detected=""; use_model="$MODEL"

# 2. OpenAI-compatible? (/v1/models then a tiny chat completion)
log "probing OpenAI-compatible surface (/v1/chat/completions)"
models_json="$(curl -s -m 5 "${auth_openai[@]}" "$base/v1/models" 2>/dev/null)"
if echo "$models_json" | grep -q '"data"'; then
  ok "/v1/models responded"
  [ -z "$use_model" ] && use_model="$(echo "$models_json" | grep -oE '"id"[ ]*:[ ]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
fi
if [ -n "$use_model" ]; then
  resp="$(curl -s -m 30 "${auth_openai[@]}" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$use_model\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with the single word: pong\"}],\"max_tokens\":8}" \
    "$base/v1/chat/completions" 2>/dev/null)"
  if echo "$resp" | grep -qiE '"content"|"choices"'; then
    detected="openai"; ok "OpenAI-style completion returned: $(echo "$resp" | tr -d '\n' | head -c 160)"
  fi
fi

# 3. Anthropic-compatible? (/v1/messages) — the likely shape for a Claude bridge
if [ -z "$detected" ]; then
  log "probing Anthropic-compatible surface (/v1/messages)"
  amodel="${use_model:-claude-sonnet-4-5}"
  resp="$(curl -s -m 30 "${auth_anthropic[@]}" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$amodel\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"reply with the single word: pong\"}]}" \
    "$base/v1/messages" 2>/dev/null)"
  if echo "$resp" | grep -qiE '"content"|"type":"message"'; then
    detected="anthropic"; use_model="$amodel"; ok "Anthropic-style completion returned: $(echo "$resp" | tr -d '\n' | head -c 160)"
  else
    no "/v1/messages did not return a completion: $(echo "$resp" | tr -d '\n' | head -c 160)"
  fi
fi

echo
if [ -z "$detected" ]; then
  log "RESULT: reachable but no completion — set MODEL (and PROXY_TOKEN if needed) and re-run."
  log "        share the proxy's docs/format if it isn't OpenAI- or Anthropic-compatible."
  exit 2
fi

log "RESULT: proxy speaks the ${detected^^} API. Handshake OK with model '$use_model'."
epoint="$base"; [ "$detected" = "openai" ] && epoint="$base/v1"
cat <<YAML

  # ---- paste into scripts/dynamodb/llm-proxy.yaml ----
  llm:
    provider: $detected
    model: $use_model
    endpoint: $epoint
    api_key_env: PROXY_API_KEY   # then: export PROXY_API_KEY='$TOK'
  # ----------------------------------------------------
YAML
