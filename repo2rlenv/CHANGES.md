# Changes — CRUCIBLE Audit Cycle

Summary of changes made during the CRUCIBLE audit and subsequent remediation pass.

## 1. CRUCIBLE Audit (REPORT.md rewrite)

Replaced the previous "Production-Readiness Audit" (manual, SHIP disposition, limited tooling) with a proper CRUCIBLE-gated audit that ran 12 of 17 instruments against the codebase.

- **Overall disposition changed**: SHIP → BLOCK (2 CRITICAL secret exposures in git history via gitleaks)
- **Instruments added**: gitleaks, mypy, shellcheck, actionlint, codespell, osv\_scanner, pip\_audit, vulture, radon (previously only ruff + bandit + radon + vulture + pip-audit-timeout)
- **Findings**: 2 CRITICAL (secrets in `.env.bak` history), 1 HIGH (torch CVE), 64 MEDIUM (mypy type errors, cyclomatic complexity, shellcheck warnings)
- **Removed stale artifacts**: deleted `BUGS.md` and `findings.json` (superseded by `findings.yaml`)

## 2. Cyclomatic Complexity Refactoring (QUA-012 / CMP-001)

Radon flagged 10 functions at complexity grade D. Refactored the three worst offenders by extracting focused helpers, each independently testable.

### `bootstrap/runner.py` — `ensure_bootstrap()` decomposed

Extracted 7 helpers from the 200+ line monolith:

| Helper | Responsibility |
|---|---|
| `_safe_emit()` | Fire phase callback, swallow exceptions |
| `_resolve_language_and_base_image()` | Language hint resolution + base image selection |
| `_check_bootstrap_cache()` | Cache-hit fast path with phase skip events |
| `_save_agent_transcript()` | Persist agent turns to `transcript.jsonl` |
| `_run_smoke_gate()` | Soft pytest smoke gate (exit 0/1/5 = OK) |
| `_ensure_git_in_image()` | Idempotent git install for downstream pipelines |
| `_make_image_tag()` | Image tag derivation from repo + spec + SHA |
| `_push_and_resolve_digest()` | Push + RepoDigest re-resolution |

`ensure_bootstrap()` now delegates to these helpers — same behavior, half the nesting.

### `cli.py` — `cmd_generate()` decomposed

Extracted 2 helpers:

| Helper | Responsibility |
|---|---|
| `_build_generate_overrides()` | Build config-override dict from argparse namespace |
| `_check_language_support()` | Fail-fast language pre-flight (returns exit code) |

### `_cli_app_synthesis.py` — `run_cli_app_pipeline()` + `_build_one_task()` decomposed

Extracted 8 helpers from the two longest functions:

| Helper | Responsibility |
|---|---|
| `_TaskRejected` | Moved to module scope (was nested at bottom) |
| `_try_emit_task()` | Shared try/except around a single task build |
| `_run_subset_mode()` | Subset emission loop (was inline in orchestrator) |
| `_run_per_command_mode()` | Per-command / per-intent loop (was inline) |
| `_compute_cliapp_task_id()` | Deterministic task\_id derivation |
| `_apply_static_gauntlet()` | G1-G2 cheap static gauntlet pass |
| `_apply_reference_grounding()` | Reference grounding filter |
| `_run_g3g4_gauntlet_gate()` | Docker gauntlet G3+G4 with rejection logic |
| `_build_cliapp_repo2env()` | Assemble repo2env metadata dict |

### `_cli_app_extract.py` — `_extract_intent_from_method()` decomposed

Extracted 4 helpers from the intent-extraction switch:

| Helper | Responsibility |
|---|---|
| `_try_cmdline_from_assignment()` | Match `cmdline = self.prefix + '...'` patterns |
| `_try_cmdline_and_rc_from_call()` | Match `self.run_cmd(...)` / `self.assert_params_for_cmd(...)` |
| `_collect_operation_names()` | Extract CamelCase API operation names from assertEqual |
| `_resolve_cmdline_with_fallbacks()` | Fallback chain: BinOp concat → regex → bare command |

## 3. Reward Clamping (defensive [0,1] invariant)

Added `_clamp_unit(value)` — clamps to `[0.0, 1.0]`, collapses NaN to 0.0.

Applied in two modules:

- **`reward.py`**: `calculate_diff_similarity_reward()` ratio, `ExecutionReport.f2p_rate`, `ExecutionReport.p2p_rate`
- **`_pr_runtime_verifier.py`** (in-container copy): `grade()` f2p\_rate and p2p\_rate

Rationale: out-of-range or NaN rewards silently poison RL training. Even though the arithmetic is bounded by construction, clamping makes the `[0, 1]` contract local and refactor-proof.

## 4. Solution Leak Detection (`_oss_instruct.py`)

New quality filter for `code_instruct` pipeline — detects when the LLM copies oracle solution lines into the problem statement (the only artifact the solving agent sees).

Two new functions:

- **`substantive_solution_lines(solution_code)`** — extracts whitespace-normalized implementation-body lines, excluding signatures, imports, docstrings, comments, and trivial keywords (`pass`, `return`, `...`)
- **`solution_leaks_into_problem(problem, solution_code)`** — counts distinct substantive lines appearing verbatim in the problem; flags as leaked if ≥ 3 lines match (or if a 1–2 line solution is fully reproduced)

The filter is wired into `CodeInstructPipeline._generate_one()` as a skip reason (`solution_leaks_into_problem`).

**Prompt hardening**: both `PROMPT_SYSTEM` and `PROMPT_SYSTEM_AWS` now explicitly instruct the LLM: *"Do NOT include the implementation, the solution source, or copies of any line from the [Solution] section."*

## 5. Type Safety Improvements

### `self._llm` instance attribute

All LLM-using pipelines (`code_instruct`, `equivalence_tests`, `mutation_bugs`) now store `self._llm = input.llm` at `__init__` and reference `self._llm` throughout instead of `self.input.llm`. This eliminates repeated Optional access on a field that's already validated as non-None at construction.

Affected: `code_instruct.py`, `equivalence_tests.py`, `mutation_bugs.py`, `_cli_app_synthesis.py`.

### `supported_languages` ClassVar on all pipelines

Added `supported_languages: ClassVar[frozenset[LanguageHint] | None] = None` to `pr_diff`, `pr_runtime`, `commit_runtime`, `cve_patches`. Previously only some pipelines declared this, causing mypy union-attr errors on the contract.

### Other type fixes

- `pr_diff.py`: `repo2env` dict annotated as `dict[str, Any]` (was bare `dict` literal, mypy dict-item errors)
- `cli.py`: `TYPE_CHECKING` guard for `BootstrapResult` and `GenerationInput` imports
- `reward.py`: explicit `list[str]` annotations on `f2p_success`, `f2p_failure`, `p2p_success`, `p2p_failure` (was bare `[]`)
- `code_instruct.py`: `assert self.bootstrap is not None` guards before Docker sandbox and harbor task assembly
- `llm.py`: blank line between imports (formatting)

## 6. New Tests

### New test files

| File | Coverage |
|---|---|
| `tests/test_bootstrap_runner.py` | +300 lines — covers all 8 extracted helpers (`_safe_emit`, `_make_image_tag`, `_run_smoke_gate`, `_save_agent_transcript`, `_check_bootstrap_cache`, `_ensure_git_in_image`, `_resolve_language_and_base_image`, `_push_and_resolve_digest`) |
| `tests/test_cli_app_extract_helpers.py` | 145 lines — covers `_try_cmdline_from_assignment`, `_try_cmdline_and_rc_from_call`, `_collect_operation_names`, `_resolve_cmdline_with_fallbacks` |
| `tests/test_cli_app_orchestrator.py` | 368 lines — covers `_try_emit_task`, `_run_subset_mode`, `_run_per_command_mode` with skip-reason bookkeeping, limit handling, dedup, per-intent fan-out |

### Expanded existing tests

| File | What was added |
|---|---|
| `tests/test_reward.py` | `_clamp_unit` boundary tests, adversarial diff-reward inputs (empty, NaN, unicode, huge), `ExecutionReport` rate invariants |
| `tests/test_pr_runtime_verifier.py` | `grade()` empty-set division-by-zero test, reward-always-in-unit-interval parametric test |
| `tests/test_oss_instruct_helpers.py` | `substantive_solution_lines` + `solution_leaks_into_problem` — 8 test cases covering leaks, non-leaks, threshold, small solutions, syntax errors |
| `tests/test_cli_app_cost.py` | Added `_llm` attribute to mock `_Pipe` |
| `tests/test_code_instruct_aws_mode.py` | Added `_llm` attribute to mock `_Pipeline` |

## 7. Dev Dependencies

Added to `pyproject.toml` dev group:
- `pip-audit>=2.10.1` — dependency vulnerability scanning
- `pyright>=1.1.410` — type checking

## 8. Cleanup

- **Deleted `BUGS.md`** — resolved findings document, superseded by `findings.yaml`
- **Deleted `findings.json`** — superseded by `findings.yaml`
- **`.gitignore`**: added `audit/` directory and UUID-named artifact directory
