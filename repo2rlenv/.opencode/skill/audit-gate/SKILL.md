---
name: audit-gate
description: "CRUCIBLE audit gate — ground every finding in tool evidence, verify with deterministic rules."
---

# audit-gate

The canonical contract lives in `CRUCIBLE.md` at the project root.
**Read it in full before any audit work.** This skill defers entirely to that document.

## Artifacts

| Artifact | Location | Purpose |
|---|---|---|
| Evidence bundle | `audit/evidence.yaml` | Machine-readable tool output (the ONLY citable source) |
| Findings | `findings.yaml` (project root) | Your analysis grounded in evidence |
| Report | `REPORT.md` (project root) | Human-readable report with Bug Tickets |

## Key Rules

- Every finding must cite evidence from `audit/evidence.yaml`.
- The verifier (`audit verify`) enforces R1 (recall), R2 (span), R3 (completed-run), R3-state, R4 (CVSS), R6 (vocabulary).
- Dispositions: `SHIP` / `HOLD` / `BLOCK` only.
- Severity: `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `INFO` / `NONE`.
- A CRITICAL-floor finding cannot be waived to SHIP.
- The gate passes only when `audit verify` exits 0.
