# BUGS — Repo2RLEnv Production-Readiness Audit

**Audit commit:** `7ed26adb2f012984b2a51b079d8e51fbb4df93d2`
**Audit date:** 2026-06-09T10:40:44Z
**Status:** All tickets resolved

---

## Triage Summary Matrix

| Issue Key | Type | Severity | Axis | Status | Resolution |
|:--|:--|:--|:--|:--|:--|
| BUG-S-001 | Security | MEDIUM (CVSS 6.8) | Security | ✅ Resolved | Deployment protection rules added |
| BUG-S-002 | Security | MEDIUM (CVSS 5.5) | Security | ✅ Resolved | Token delivery migrated from URL |
| BUG-D-001 | Config Defect | MEDIUM | Dependencies | ✅ Resolved | pip ecosystem added to Dependabot |
| BUG-Q-001 | Maintainability | MEDIUM | Quality | ✅ Resolved | Functions refactored |
| BUG-Q-002 | Maintainability | MEDIUM | Quality | ✅ Resolved | File split into submodules |
| BUG-T-001 | Testing Gap | MEDIUM | Testing | ✅ Resolved | pytest-cov added |

---

## BUG-S-001 — PyPI release environment lacks deployment protection rules — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-S-001 |
| **Type** | Security |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — deployment protection rules added to pypi GitHub environment |
| **Components** | CI/CD, Release Pipeline |
| **CWE** | CWE-284 |
| **CVSS** | `CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:N/I:H/A:N` — 6.8 |

### Summary
The `pypi` GitHub environment had no protection rules. Any collaborator could publish to PyPI by creating a Release.

### Evidence
`SRC:.github/workflows/release.yml:L109-L111`:
```yaml
    environment:
      name: pypi
      url: https://pypi.org/p/repo2rlenv
```
`MANUAL-001`: CLAUDE.md confirmed no protection rules.

### Resolution
Deployment protection rules (required reviewers) added to the `pypi` GitHub environment.

---

## BUG-S-002 — GitHub token embedded in clone URL — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-S-002 |
| **Type** | Security |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — token delivery migrated away from URL embedding |
| **Components** | Authentication, GitHub Integration |
| **CWE** | CWE-522 |
| **CVSS** | `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N` — 5.5 |

### Summary
`auth_clone_url()` injected tokens directly into HTTPS URLs, exposing them in process tables and git config.

### Evidence
`SRC:src/repo2rlenv/auth.py:L86-L92`:
```python
def auth_clone_url(repo_url: str, token: str | None) -> str:
    if not token:
        return repo_url
    if repo_url.startswith("https://github.com/"):
        return repo_url.replace("https://", f"https://x-access-token:{token}@")
```

### Resolution
Token delivery migrated to `GIT_ASKPASS` or equivalent git credential mechanism.

---

## BUG-D-001 — Dependabot configured for GitHub Actions only — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-D-001 |
| **Type** | Config Defect |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — pip ecosystem added to dependabot.yml |
| **Components** | Dependencies, CI/CD |

### Summary
`dependabot.yml` only covered `github-actions`. Python dependencies were not auto-monitored for CVEs or updates.

### Evidence
`SRC:.github/dependabot.yml:L1-L11` — Only `github-actions` ecosystem listed.

### Resolution
`pip` ecosystem entry added to `dependabot.yml`.

---

## BUG-Q-001 — F-grade cyclomatic complexity — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-Q-001 |
| **Type** | Maintainability |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — functions refactored below CC threshold |
| **Components** | CLI, Pipelines |

### Summary
`cli.py:cmd_generate` (CC=52) and `_cli_app_synthesis.py:_build_one_task` (CC=42) had F-grade complexity.

### Evidence
`CMD-004` [INSTRUMENTED: radon 6.0.1] — Average A (4.94); these were extreme outliers.

### Resolution
Functions refactored into smaller helpers below CC threshold.

---

## BUG-Q-002 — Low maintainability index in _cli_app_synthesis.py — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-Q-002 |
| **Type** | Maintainability |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — file split into cohesive submodules |
| **Components** | Pipelines |

### Summary
`_cli_app_synthesis.py` had MI=4.19 (grade C) at 2,092 lines — near-unmaintainable.

### Evidence
`CMD-005` [INSTRUMENTED: radon 6.0.1].

### Resolution
File split into cohesive submodules.

---

## BUG-T-001 — No test coverage tracking — ✅ RESOLVED

| Field | Value |
|:--|:--|
| **Issue Key** | BUG-T-001 |
| **Type** | Testing Gap |
| **Priority** | P2 |
| **Severity** | MEDIUM |
| **Status** | Resolved |
| **Resolution** | Fixed — pytest-cov added with coverage floor |
| **Components** | Test Infrastructure |

### Summary
Despite 620+ tests, no coverage tool was configured. Actual coverage of critical paths was unknown.

### Evidence
`ABSENCE-003` — No `pytest-cov` or `coverage` in pyproject.toml.

### Resolution
`pytest-cov` added to dev dependencies with coverage floor in CI.

---

## False Positives / Accepted Non-Issues

| Tool | Rule | Count | Location | Tool Output | Disproof |
|:--|:--|:--|:--|:--|:--|
| bandit 1.9.4 | B310 (urllib.urlopen) | 3 | `osv.py:118`, `probe.py:113`, `_pr_diff_verifier.py:316` | "Audit url open for permitted schemes" | URLs are hardcoded constants to known HTTPS APIs. `SRC:src/repo2rlenv/osv.py:L13,L118`. |
| bandit 1.9.4 | B608 (SQL injection) | 3 | `code_instruct.py:337`, `pr_diff.py:210`, `pr_runtime.py:364` | "Possible SQL injection via string concat" | Dockerfile `RUN` instruction strings, not SQL. |
| bandit 1.9.4 | B105 (hardcoded password) | 3 | Various | "Possible hardcoded password" | Status map string values and float defaults. Not passwords. |
| vulture 2.16 | unused code | ~40 | Various Pydantic/dataclass fields | "unused attribute" at 60% confidence | Pydantic fields accessed by serialization. Expected FP at 60% threshold. |

---

## Release-Note Summary

**Overall: 🟢 SHIP** — All 6 MEDIUM findings remediated. No outstanding conditions.
