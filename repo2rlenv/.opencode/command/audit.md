---
description: "Run the CRUCIBLE audit gate — provision, scan, write findings, verify."
agent: build
---

# /audit — CRUCIBLE Audit Gate

The canonical contract lives in `@CRUCIBLE.md` at the project root.
Read it **in full** before proceeding. This command is a thin wrapper.

## Phase 1 — Instrument & Collect Evidence

```bash
uv run --project audit audit all -t 900
```

This provisions scanners, runs all instruments, and writes `audit/evidence.yaml`.
It does **not** write findings — that is your job (Phase 2).

## Phase 2 — Write Findings + Report

1. Read `@REVIEW.md` for the full Phase-2 instruction set.
2. Read `@audit/evidence.yaml` as the **ONLY** source of instrumented evidence.
3. Write `findings.yaml` at the project root (schema: list of Finding dicts).
4. Write `REPORT.md` at the project root (the single human report, with Bug Tickets section).

Strip `_template` / `_example` keys. `REPORT.md` is the deliverable.

## Phase 3 — Verify

```bash
uv run --project audit audit verify --findings findings.yaml --context audit/evidence.yaml
```

The gate passes **only** when `audit verify` exits `0`.
Findings are **UNGATED** until that happens.
