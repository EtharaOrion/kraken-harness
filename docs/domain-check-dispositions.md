# Domain Check — Dispositions

Static analysis domain checks flagged 3 issues across 2 rules. After manual
review against the Harbor runtime source: **DOM-002 surfaced one legitimate
gap** (a missing guard, now fixed) plus framing noise; **DOM-003 is a confirmed
false positive**.

---

## DOM-002: dataset_leakage_check — oracle leakage (2 issues)

### Harbor's solve-time visibility model (the governing fact)

Verified against the Harbor source (`models/trial/paths.py`, `oracle.py`,
`verifier.py`, `single_step.py`). At **solve time**, the only artifact mounted
into the solving agent's container is `instruction.md`. Both the oracle
solution and the test are withheld:

- `solution/` — "Copied over by the OracleAgent only" (the solving agent never
  receives it).
- `tests/` — "Copied over by the Verifier **after** the agent runs."

Execution order is: agent runs → artifacts collected → verifier runs. This is
the standard SWE-bench convention (held-out oracle, hidden verifier).

### 1. `harbor.py` — FALSE POSITIVE (emission separation is correct)

The emitter writes two isolated artifacts:

- `instruction.md` from `task.instruction` (line 149) — agent-visible
- `solution/patch.diff` from `task.oracle_diff` (line 154) — oracle-only,
  transiently copied to the OracleAgent only

The `solution/` path is never mounted for the solving agent (see model above).
Comments referencing the oracle document the architecture, not a leakage vector.
No code change needed here.

### 2. `code_instruct.py` — LEGITIMATE GAP (now fixed)

**The real risk.** Because the test and oracle are both withheld at solve time,
the *only* contamination vector that can actually reach the agent is the
**oracle solution bleeding into the problem statement** (`parsed.problem`, the
sole agent-visible field). The pipeline generates problem + test + solution in a
single LLM call, so a chatty model can echo implementation lines straight into
the problem text — and there was **no guard against this**. The existing
decontamination block only checked `has_benchmark_overlap` (eval-benchmark
phrases), never self-leakage of solution → problem.

**Fix (this change):**

1. New guard `solution_leaks_into_problem()` in `_oss_instruct.py` — extracts
   the substantive implementation lines from the oracle (excluding signatures,
   imports, docstrings, comments, and trivial one-keyword lines) and rejects the
   candidate if ≥3 distinct lines appear verbatim in the problem (or if a 1–2
   line body is fully reproduced). New skip reason: `solution_leaks_into_problem`.
2. Wired into the decontamination block in `code_instruct.py`, alongside the
   existing benchmark-overlap check (gated by the same `skip_decontamination`).
3. Prompt hardening: both `PROMPT_SYSTEM` and `PROMPT_SYSTEM_AWS` now explicitly
   forbid copying any line of the `[Solution]` section into the
   `[Problem Description]` (defense-in-depth at generation time).
4. Unit tests in `tests/test_oss_instruct_helpers.py` cover the leak-detected,
   clean-problem, threshold-boundary, small-solution, and syntax-error cases.

---

## DOM-003: container_surface_check (1 issue)

### 1. `agent.py` — "No container cleanup found"

**Why it's a false positive:**

The checker scoped its analysis to `agent.py` alone and missed the ownership boundary. `run_agent_loop()` (line 155) receives `sandbox: DockerSandbox` as a **parameter** — it is a pure consumer that never creates or destroys containers.

Container lifecycle is owned by the caller. Every `DockerSandbox.start()` call site in the codebase has a cleanup guarantee:

| Call site | File | Cleanup mechanism |
|---|---|---|
| `runner.py:698` | bootstrap runner | `with` context manager |
| `pr_runtime.py:1027` | PR runtime pipeline | `try/finally` (lines 930–932) |
| `code_instruct.py:635` | code instruct pipeline | `try/finally` (lines 592–594) |
| `commit_runtime.py:424` | commit runtime pipeline | `try/finally` (lines 350–352) |
| `cve_patches.py:286` | CVE patches pipeline | `try/finally` (lines 267–269) |
| `mutation_bugs.py:462` | mutation bugs pipeline | `try/finally` (lines 426–428) |
| `equivalence_tests.py:394` | equivalence tests pipeline | `try/finally` (lines 350–352) |
| `runner.py:296` | `_verify_committed_image` | `docker run --rm` flag |

All 8 sites confirmed — no container leak exists.

---

## Recommendation

- **DOM-002 / `code_instruct.py`**: resolved in code — the missing
  solution→problem guard is now implemented and tested. No suppression needed;
  the checker correctly pointed at a real gap.
- **DOM-002 / `harbor.py`** and **DOM-003 / `agent.py`**: false positives.
  Suppress via allowlist/suppression comments or by documenting the disposition
  here and skipping re-triage on subsequent runs.

Do not remove domain terms ("solution", "oracle") from code or docstrings to
silence a pattern matcher — that degrades documentation without fixing anything.
The remaining flags reflect the checker's lack of cross-module / cross-repo
(Harbor runtime) visibility, not real leakage.
