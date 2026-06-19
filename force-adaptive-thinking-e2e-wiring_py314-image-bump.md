# Raiden Project — Nightshift → Dayshift Handoff

**Author:** Piyush Chandra (`piyush.chandra@ethara.ai`)
**Date:** 2026-06-19
**Scope:** Cross-repo changes wiring `force_adaptive_thinking` through the Raiden stack, plus Python 3.14 upgrade in dataset images and a Harbor pin.

---

## TL;DR

A new opt-in flag, **`force_adaptive_thinking`**, has been threaded end-to-end from the trajectory CLI down to the LLM construction inside the OpenHands SDK container. It is required for **Claude Opus 4.7/4.8 and Fable 5** to emit populated `thinking` blocks. In parallel, the `raiden-dataset` Docker images were bumped from **Python 3.12 → 3.14** and repointed to ECR.

Flow of the new flag:

```
raiden-trajectory-general.sh  --force-adaptive-thinking
        │
        ▼
Harbor OpenHandsSDK agent  (LLM_FORCE_ADAPTIVE_THINKING=1 env var into container)
        │
        ▼
openhands_sdk_runner  (force_adaptive_thinking=True → LLM(**llm_kwargs))
        │
        ▼
software-agent-sdk LLM layer  (chat_options → top-level output_config payload)
```

---

## 1. `Repo2RLEnv` (this repo)

| # | Hash | Type | Summary |
|---|------|------|---------|
| 1 | `0ff6900` | Config/deps | Pinned Harbor dependency, added `raiden-sa.json` to `.gitignore`, updated `pyproject.toml` + `uv.lock`. 3 files, **+772 / −44** (mostly lockfile churn). |
| 2 | `3db2a49` | Feature | `feat(raiden-trajectory): add --force-adaptive-thinking flag` — new CLI flag on `raiden-trajectory-general.sh`. 1 file, **+6 lines**. |

**Notes for dayshift:**
- `raiden-sa.json` is now gitignored — make sure local service-account creds aren't accidentally re-added.
- Harbor is pinned; if the Harbor PR (see §4) lands and gets a new release tag, this pin will need a bump.
- The `--force-adaptive-thinking` CLI flag is the user-facing entry point for the whole flag chain.

---

## 2. `raiden-dataset`

| Commit | Subject |
|--------|---------|
| `ac0f233` | Bump Dockerfiles from Python 3.12 → 3.14 |
| `9ace0a7` | Point base image to ECR |
| `b503e8f` | Edit Dockerfiles |
| `f19e407` | Bump Python version to 3.14 across `task.toml` and `instruction.md` |

**Notes for dayshift:**
- Full Python 3.12 → 3.14 upgrade across image build + task metadata + docs.
- Base image now sourced from **ECR** (not public registry). Confirm CI/runner roles have ECR pull permissions before mass re-runs.
- Validate any tasks pinned to 3.12-specific behavior; rerun a sample task end-to-end before promoting.

---

## 3. `software-agent-sdk`

All commits dated **2026-06-19** under `piyush.chandra@ethara.ai`.
(No commits found under `piyush.chandra2013@gmail.com` — flagging in case anyone goes looking.)

### 3.1 `de3335ce` — `feat(sdk/llm): add force_adaptive_thinking opt-in flag`
**+109 lines across 4 files**

- `openhands-sdk/openhands/sdk/llm/llm.py` (+13)
- `openhands-sdk/openhands/sdk/llm/options/chat_options.py` (+25)
- `openhands-sdk/openhands/sdk/llm/utils/model_features.py` (+12)
- `tests/sdk/llm/test_chat_options.py` (+59)

Introduces the opt-in `force_adaptive_thinking` flag in the SDK's LLM layer, wired through chat options and model-feature detection, with corresponding unit tests.

### 3.2 `77ee8a7c` — `fix(sdk/llm): emit output_config at top level for adaptive thinking`
**+12 / −18 across 2 files**

- `openhands-sdk/openhands/sdk/llm/options/chat_options.py`
- `tests/sdk/llm/test_chat_options.py`

Follow-up fix to 3.1: restructures the adaptive-thinking payload so `output_config` is emitted at the **top level** rather than nested. Tests updated to reflect the new shape.

**Notes for dayshift:**
- If anything downstream was reading `output_config` from a nested location, it will now find it at the top level — watch for stale consumers.
- Two of the five commits today were substantive; the rest were not flagged as material — ask Piyush if you need the full list before touching the LLM layer.

---

## 4. `Harbor`

### `efa0ba77` — `feat(openhands_sdk): forward force_adaptive_thinking kwarg to container`
**2 files changed, +10 lines · 2026-06-19**

Wires the new `force_adaptive_thinking` flag through the OpenHands SDK agent so host-side configuration propagates into container-side LLM construction.

**Changes:**

- `src/harbor/agents/installed/openhands_sdk.py`
  - Added `force_adaptive_thinking: bool = False` to `OpenHandsSDK.__init__`.
  - Stored on `self._force_adaptive_thinking`.
  - When enabled, sets container env var `LLM_FORCE_ADAPTIVE_THINKING="1"` before launching the runner.
  - Docstring notes: required for **Claude Opus 4.7 / 4.8 / Fable 5** to return populated thinking blocks.
- `src/harbor/agents/installed/openhands_sdk_runner.py`
  - Reads `LLM_FORCE_ADAPTIVE_THINKING` env var (accepts `1` / `true` / `yes`).
  - When truthy, injects `force_adaptive_thinking=True` into `LLM(**llm_kwargs)`.

**Purpose:** Enables adaptive thinking at the LLM layer for newer Claude models that require it to emit thinking blocks, controllable **per-agent invocation** without code changes inside the container.

**Notes for dayshift:**
- The env-var bridge (`LLM_FORCE_ADAPTIVE_THINKING`) is the contract between host and container. If you change the name, both files in §4 *and* the runner read in `software-agent-sdk` need to be updated together.
- Default is `False` — existing agents are unaffected unless they opt in.

---

## End-to-End Validation Checklist (for dayshift)

- [ ] Run `raiden-trajectory-general.sh --force-adaptive-thinking` against a Claude Opus 4.7/4.8 (or Fable 5) target and confirm `thinking` blocks are populated in the trajectory output.
- [ ] Run the same script **without** the flag against a non-adaptive model and confirm no regression (default-off behavior preserved).
- [ ] Rebuild a `raiden-dataset` image on Python 3.14 from ECR and execute one representative task end-to-end.
- [ ] In `software-agent-sdk`, run `tests/sdk/llm/test_chat_options.py` to confirm the top-level `output_config` shape.
- [ ] Verify `raiden-sa.json` is **not** present in the working tree of `Repo2RLEnv`.

---

## Open Questions / Risks

1. **Model gating** — the flag is required for Opus 4.7/4.8 and Fable 5; behavior on other models is opt-in but unverified at scale. Worth a smoke test across the active model roster.
2. **Harbor pin** — pinned in `Repo2RLEnv` to capture the new kwarg. Coordinate any Harbor release bump with the consumer pin.
3. **Python 3.14 surface area** — third-party deps in `raiden-dataset` images may not all have 3.14 wheels yet; watch the first full CI run for build failures.
4. **ECR permissions** — confirm all runner identities can pull from ECR after the base image repoint.

---

## Contacts

- **Author:** Piyush Chandra — `piyush.chandra@ethara.ai`
- **Repos touched:** `Repo2RLEnv`, `raiden-dataset`, `software-agent-sdk`, `Harbor`
