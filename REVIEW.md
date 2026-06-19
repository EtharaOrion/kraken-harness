# Phase 2 — Findings & Report

You are the auditor. Your inputs are this file and `audit/evidence.yaml`.
Your outputs are `findings.yaml` and `REPORT.md`, both at the project root.
The canonical contract is `CRUCIBLE.md` — read it before starting.

## Your Task

1. Read `audit/evidence.yaml` — this is the **ONLY** source of instrumented evidence you may cite.
2. Triage every `normalized_issue` with severity >= MEDIUM. Acknowledge each by `issue_instance_id` or `cluster_fingerprint`.
3. Write `findings.yaml` — a YAML list of Finding objects (see schema below).
4. Write `REPORT.md` — the single human report with a **Bug Tickets** section.
5. Run `uv run --project audit audit verify --findings findings.yaml --context audit/evidence.yaml` and iterate until it exits 0.

## findings.yaml Schema

```yaml
- id: "SEC-001"
  title: "Short descriptive title"
  severity: "HIGH"           # CRITICAL | HIGH | MEDIUM | LOW | INFO | NONE
  category: "security"       # security | dependency | quality | style | documentation
  description: "What the issue is and why it matters."
  evidence: "Cite specific tool/rule_id from evidence.yaml"
  recommendation: "Concrete fix."
  disposition: "HOLD"        # SHIP | HOLD | BLOCK
  affected_files:
    - "path/to/file.py"
  issue_count: 3
  source_tools:
    - "bandit"
```

## Verifier Rules (what `audit verify` checks)

| Rule | What it checks |
|---|---|
| **provenance** | Manifest integrity — evidence, scope, command, source |
| **R1** | Every normalized issue with severity >= MEDIUM is acknowledged in findings |
| **R2** | Every `path:line` in issues resolves (source/secret/config/artifact need path; dependency needs package) |
| **R3** | Blocked/timed-out BLOCK-level tools are flagged as coverage gaps |
| **R3-state** | SHIP requires: non-null git SHA + clean tree + pinned scanner DBs |
| **R4** | Issues with `vuln_id` must have severity != NONE |
| **R6** | Only valid severity/disposition/state vocabulary used |

## CRITICAL Floor (cannot be waived to SHIP)

Injection, unsafe deserialization, SSRF, authz bypass, secret exposure, memory corruption,
CVSS >= 9 or KEV, container escape, dataset leakage, agent-writable reward, rollout miscount.

## Waiver Discipline

- LOW/MEDIUM: inline rationale sufficient.
- HIGH/CRITICAL/security: requires out-of-band approved waiver with reason-code enum + fingerprint-bound rationale.
- Boilerplate reused across unrelated fingerprints is rejected.

## Disposition Rules

- **SHIP**: All required instruments ran clean, all issues acknowledged, clean tree, pinned DBs.
- **HOLD**: Missing instrument, unpinned DB, self-attested provenance, or >= HIGH unresolved.
- **BLOCK**: Failed integrity check, CRITICAL-floor finding, or BLOCK-level coverage gap.

## Anti-Patterns (will fail verification)

- Citing evidence not in `audit/evidence.yaml`
- Omitting a >= MEDIUM issue from findings
- Using dispositions/severities outside the allowed vocabulary
- Issues with `vuln_id` but severity = NONE
- `_template` / `_example` keys in output
