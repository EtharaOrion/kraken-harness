# CRUCIBLE Audit Report — Repo2RLEnv

**Date**: 2026-06-19  
**Git SHA**: `621f611fa105bd470b3e5ab5b16f8734443657d5` (dirty tree)  
**Overall Disposition**: **BLOCK**  
**Evidence**: `audit/evidence.yaml`  
**Findings**: `findings.yaml`

## Executive Summary

This audit ran 12 of 17 required instruments against Repo2RLEnv at the above SHA. Two **CRITICAL** secret exposure findings in git history force the overall disposition to **BLOCK**. Additionally, 1 HIGH dependency vulnerability and 64 MEDIUM quality issues (mypy type errors, cyclomatic complexity, shellcheck warnings) produce a **HOLD** floor independent of the secrets.

SHIP is mechanically unreachable for three independent reasons:
1. CRITICAL-floor secret findings (BLOCK)
2. Dirty working tree (R3-state → HOLD)
3. Self-attested provenance — no external trust root key (provenance → HOLD)

## Findings Summary

| ID | Severity | Tool | Count | Disposition | Title |
|---|---|---|---|---|---|
| SEC-001 | CRITICAL | gitleaks | 1 | BLOCK | GitHub PAT exposed in .env.bak |
| SEC-002 | CRITICAL | gitleaks | 1 | BLOCK | Generic API key exposed in .env.bak |
| DEP-001 | HIGH | pip_audit | 1 | HOLD | torch 2.6.0 CVE-2025-3000 |
| QUA-001 | MEDIUM | mypy | 12 | HOLD | union-attr: optional access without narrowing |
| QUA-002 | MEDIUM | mypy | 7 | HOLD | assignment: incompatible types |
| QUA-003 | MEDIUM | mypy | 6 | HOLD | dict-item: incompatible dict entries |
| QUA-004 | MEDIUM | mypy | 6 | HOLD | arg-type: incompatible arguments |
| QUA-005 | MEDIUM | mypy | 5 | HOLD | index: unsupported indexed assignment |
| QUA-006 | MEDIUM | mypy | 5 | HOLD | call-overload: no matching overload |
| QUA-007 | MEDIUM | mypy | 4 | HOLD | var-annotated: missing annotations |
| QUA-008 | MEDIUM | mypy | 1 | HOLD | operator: float * None |
| QUA-009 | MEDIUM | mypy | 1 | HOLD | misc: generator type mismatch |
| QUA-010 | MEDIUM | mypy | 1 | HOLD | return-value: incompatible return |
| QUA-011 | MEDIUM | mypy | 1 | HOLD | no-redef: conditional import |
| QUA-012 | MEDIUM | radon | 10 | HOLD | complexity-D in 10 functions |
| QUA-013 | MEDIUM | shellcheck | 3 | HOLD | SC1090: non-constant source |
| QUA-014 | MEDIUM | shellcheck | 1 | HOLD | SC2221: overriding case pattern |
| QUA-015 | MEDIUM | shellcheck | 1 | HOLD | SC2222: unreachable case pattern |

**Totals**: 2 CRITICAL, 1 HIGH, 64 MEDIUM = 67 issues acknowledged (of 164 total; 97 LOW/INFO not requiring acknowledgment per R1 ≥MEDIUM threshold).

## Instrument Coverage

| Tool | Status | Issues | Notes |
|---|---|---|---|
| ruff | ✅ ran | 0 | Clean |
| ruff_format | ✅ ran | 0 | Clean |
| bandit | ✅ ran | 0 | Clean (86 LOW confidence, filtered) |
| mypy | ✅ ran | 49 | 49 MEDIUM type errors |
| vulture | ✅ ran | 35 | All INFO (dead code hints) |
| radon | ✅ ran | 10 | 10 MEDIUM complexity-D |
| pip_audit | ✅ ran | 1 | 1 HIGH (torch CVE) |
| shellcheck | ✅ ran | 32 | 5 MEDIUM, 27 LOW/INFO |
| gitleaks | ✅ ran | 2 | 2 CRITICAL (secrets in history) |
| actionlint | ✅ ran | 0 | Clean |
| codespell | ✅ ran | 35 | All LOW (typos) |
| osv_scanner | ✅ ran | 0 | Clean |
| semgrep | ❌ missing | — | HOLD cap (critical_capable) |
| trufflehog | ❌ missing | — | HOLD cap (critical_capable) |
| shfmt | ❌ missing | — | SHIP cap |
| yamllint | ❌ missing | — | SHIP cap |
| markdownlint | ❌ missing | — | SHIP cap |

## Coverage Gaps

1. **semgrep** — Binary not installed. SAST taint analysis (OWASP/secrets packs) not run. Install: `pip install semgrep`. Disposition cap: HOLD.
2. **trufflehog** — Binary not installed. Entropy-based secret scanning not run. Install: `brew install trufflehog`. Disposition cap: HOLD.
3. **shfmt** — Shell formatter not installed. Install: `brew install shfmt`. Non-blocking.
4. **yamllint** — YAML linter not installed. Install: `pip install yamllint`. Non-blocking.
5. **markdownlint** — Markdown linter not installed. Install: `npm install -g markdownlint-cli2`. Non-blocking.
6. **codeql** — Not in tool registry; CLI may not be available locally. Semgrep provides overlapping taint coverage. Declared scope gap.
7. **`.crucible/semgrep` custom rules** — Harbor-domain taint rules (reward reads outside verifier, agent-path reward writes) not authored. D-COVERAGE-GAP.

## Bug Tickets

### SEC-001: Rotate and purge GitHub PAT from .env.bak [CRITICAL/BLOCK]

**Priority**: P0 — Immediate action required  
**Affected**: `.env.bak` in git history  
**Tool**: gitleaks/github-pat  
**Cluster**: `178bef5355db8b41`

A GitHub Personal Access Token was found committed in `.env.bak`. Even if the file was later deleted, the token remains in git history and can be extracted by anyone with clone access.

**Action items**:
1. Rotate the PAT on GitHub immediately
2. Run `git filter-repo --path .env.bak --invert-paths` or use BFG to purge from history
3. Force-push the cleaned history to all remotes
4. Audit GitHub audit log for unauthorized access using the token
5. Ensure `.env.bak` is in `.gitignore`

---

### SEC-002: Rotate and purge generic API key from .env.bak [CRITICAL/BLOCK]

**Priority**: P0 — Immediate action required  
**Affected**: `.env.bak` in git history  
**Tool**: gitleaks/generic-api-key  
**Cluster**: `d4d20b0f37cfb58e`

A generic API key (likely for a cloud service) was found in the same `.env.bak` file. Same remediation as SEC-001.

**Action items**:
1. Identify which service the key belongs to and rotate it
2. Same history-purge steps as SEC-001

---

### DEP-001: Upgrade torch to fix CVE-2025-3000 [HIGH/HOLD]

**Priority**: P1  
**Affected**: `torch` package (transitive dependency)  
**Tool**: pip_audit/vulnerable-dependency  
**CVE**: CVE-2025-3000  
**Cluster**: `43fd3b952b430936`

PyTorch 2.6.0 has a critical vulnerability in `torch.jit.script`. While torch is a transitive dependency (not directly declared), it's resolved in the environment.

**Action items**:
1. Check if torch is actually used at runtime (it may be pulled by a dependency like `google-cloud-aiplatform`)
2. If needed, pin `torch>=<fixed_version>` in `pyproject.toml` constraints
3. If torch is not needed, exclude it via dependency resolution

---

### QUA-001 through QUA-011: Fix 49 mypy type errors [MEDIUM/HOLD]

**Priority**: P2  
**Affected**: 10 source files (primarily pipeline code)  
**Tool**: mypy (11 distinct rule violations)

The project declares `py.typed` and uses type checking, but 49 type errors remain. The most impactful categories:
- **union-attr** (12): Accessing attributes on Optional types without None checks — runtime crash risk
- **assignment** (7): Type mismatches in variable assignments
- **arg-type** (6): Passing Optional where non-Optional is expected
- **dict-item** (6): Dict entry type mismatches
- **operator** (1): `float * None` in verifier — direct runtime crash risk

**Action items**:
1. Focus on `union-attr` and `operator` first (runtime crash risk)
2. Add None guards or narrow types systematically
3. Consider `--strict` mode incrementally

---

### QUA-012: Reduce cyclomatic complexity in 10 functions [MEDIUM/HOLD]

**Priority**: P3  
**Affected**: 7 source files  
**Tool**: radon/complexity-D (scores 21-30)

Long orchestration functions with deep nesting. Affects testability and maintainability. Key offenders: `hub.py`, `cli.py`, pipeline `run()` methods.

**Action items**:
1. Extract helper functions from complex orchestrators
2. Target complexity rank C (≤20) or better

---

### QUA-013 through QUA-015: Fix 5 shellcheck warnings [MEDIUM/HOLD]

**Priority**: P3  
**Affected**: 3 shell scripts (`raiden-*.sh`)  
**Tool**: shellcheck (SC1090, SC2221, SC2222)

- SC1090: Non-constant `source` paths prevent shellcheck from analyzing sourced scripts
- SC2221/SC2222: Dead case pattern in `raiden-trajectory-general.sh` (one pattern overrides another)

**Action items**:
1. Add `# shellcheck source=<path>` directives
2. Fix the overlapping case patterns on line 232

## Provenance

- **Manifest**: `audit/provenance.manifest.yaml`
- **Trust level**: Self-attested (no external trust root key)
- **Disposition cap from provenance**: HOLD (SHIP requires external signature)
- **R3-state**: HOLD (dirty working tree)

## Verification

Run the gate:
```bash
uv run --project audit audit verify --findings findings.yaml --context audit/evidence.yaml
```

Loop until exit 0. Current state: UNGATED (findings not yet verified).
