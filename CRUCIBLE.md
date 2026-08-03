# CRUCIBLE — scope any project, then scaffold an adversarial audit gate

> **What this is.** A single, self-contained, copy-paste **scaffolding prompt** — this is the **canonical way to bootstrap a CRUCIBLE audit gate**. Paste everything under [THE PROMPT](#the-prompt) into any coding agent (opencode, hermes-agent, kiro, cursor, Claude Code, or drive it by hand) at the **root of any project**. It first *discovers and scopes* what the project actually contains, then *scaffolds an adversarial audit gate* tailored to that project. It assumes nothing about the layout.
>
> **The canonical lifecycle.** **Bootstrap** (paste THE PROMPT → Phase 0 scope) → **sign off** (Phase 0.5 scope-hash approval) → **scaffold** (Phase 1 generates the `audit/` harness) → **self-verify** (Phase 2) → **upgrade** (edit this file at the root and re-run; an UPDATE run reconciles the existing harness instead of re-scaffolding). There is no other supported entry point: scaffolding a gate, and upgrading one, both happen by running this prompt.
>
> **Where this lives.** `CRUCIBLE.md`'s canonical home is the **project root**, and it is the single source of truth for the audit **contract**. Developers **edit this file at the root and re-run the prompt to upgrade the audit harness**: an UPDATE run (Phase 0, step 0) detects the existing `audit/` harness, re-derives scope, and *reconciles* the harness against the edited spec rather than re-scaffolding from scratch. The **run playbook** (how to provision/run/verify) and the **full rationale** (the MECE partition, formal-policy reframe, trusted-evidence axiom, threat model, drift-ledger theory) live in [`audit/README.md`](audit/README.md). This file is deliberately lean — it is the prompt, not the textbook.

---

## The contract in one screen

A CRUCIBLE gate is a **CRITICAL-recall gate**, not an oracle of correctness. A green gate means *"the producer's report is internally honest, survives mechanical cross-checks, and every required CRITICAL-capable instrument ran, parsed, and surfaced no unacknowledged CRITICAL"* — **never** *"the deliverable is correct."* Absence of a finding under declared coverage **supports** a clean disposition; it never **proves** safety.

- **Fail closed.** When a required CRITICAL-capable instrument does not run, cannot be parsed, or does not cover a present surface, the disposition is **capped at `HOLD` or `BLOCK`, never `SHIP`**. A coverage gap is a finding, never a silence.
- **The producer is the adversary.** Whoever fills in the findings has read this gate and is rewarded for `SHIP`, not for truth. Design every rule against a motivated liar smarter than the gate author.
- **Dispositions are strictly `SHIP` / `HOLD` / `BLOCK`.** Severity (`INFO`/`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) is independent of disposition.

**The six CRITICAL classes the gate must be built to catch** (not hygiene lint — these kill an agent-eval framework):

1. **Code execution & injection** — SQL/command/template injection, unsafe deserialization, SSRF, path traversal, `eval`/`exec` on untrusted input (taint-aware SAST, not lint).
2. **Authn / authz / trust-boundary** — privilege escalation, missing authz, and *here* the agent-vs-verifier boundary (an agent that can write the reward file or mutate the verifier's tests/scripts).
3. **Secret exposure** — valid credentials in the working tree **and in full git history** (a token committed once and later deleted still ships in the clone).
4. **Memory safety** — use-after-free, OOB, overflow in C/C++; reachable `unsafe` unsoundness in Rust.
5. **Supply chain** — dependency CVEs with CVSS ≥ 9 / KEV / known RCE across every ecosystem, plus container CVEs and misconfig.
6. **Domain integrity** (the defects no off-the-shelf scanner sees) — train/test **dataset leakage**, a **reward-hacked or agent-writable reward**, a **dropped/duplicated/miscounted rollout**, and a **report metric that does not reconcile** with the raw trial artifacts. These are *required, first-class, deterministic* checks (§1.5), not afterthoughts.

**Deterministic harness vs. non-deterministic judgment (the load-bearing partition).** Every audit obligation is decomposed into atomic predicates and bucketed:

- **Bucket D (the harness owns this; an LLM may never do it).** The atom is a **total, bounded, deterministic relation over the Phase-1 grounded artifacts and the approved hash-bound policy**, producing one canonical answer (a hash, a parse, an arithmetic recomputation, a set/multiset membership test, a scanner exit code). If a required D-atom has no passing implementation it is a **`D-COVERAGE-GAP`** — still owned by the harness, **caps the disposition, and is never laundered into Bucket N**.
- **Bucket N (an LLM may do this; the harness cannot).** The irreducibly semantic residual — exploitability, severity honesty, CWE appropriateness, rationale truth, remediation adequacy, relevance, policy adequacy. Every Bucket-N atom declares exactly one of five **reason-code families**: `trusted-runner`, `semantic-truth`, `policy-adequacy`, `scanner-soundness`, `clustering-semantics`. The model judges *on top of* a verified substrate; it never re-derives a fact the harness already owns.

> "An OSS tool exists" is **not** the test for Bucket D — *specifiability as a total bounded recomputable relation* is. Missing machinery is a gap in the harness, never a promotion to judgment. The full MECE theory, the formal-policy reframe, the trusted-evidence axiom, and the producer-bypass table are in [`audit/README.md`](audit/README.md).

**Artifacts (machine format → YAML, human format → Markdown):**

| Artifact | Format | Who writes it | Committed? |
|---|---|---|---|
| `audit/evidence.yaml` | YAML (machine) | the harness (`audit run`) | **yes** — the single evidence bundle; the **only** source a reviewer/LLM may cite |
| `findings.yaml` | YAML (machine) | the Phase-2 model | yes |
| `REPORT.md` | Markdown (human) | the Phase-2 model | yes — the **single canonical human report**; its **Bug Tickets** section holds the JIRA-style tickets, false-positive ledger, and triage matrix, with color-flag emojis |
| `REVIEW.md` | Markdown (human) | shipped with the gate | yes — the Phase-2 instruction prompt the model reads |
| `audit/scope.yaml` + `audit/scope.approved` | YAML + digest | Phase 0 / human approver | yes — the scope-sign-off gate |
| `audit/results/artifacts/CMD-NNN.stdout.txt` | text (raw) | the runner | **no** — gitignored; volatile per-command transcripts |

There is **no** `AUDIT.md`, **no** `BUGS.md` (folded into `REPORT.md`), and **no** separate `SCOPE.md` (the YAML is read directly).

- **Run:** `uv run --project audit audit all -t 900`
- **Verify (the gate):** `uv run --project audit audit verify --findings findings.yaml --context audit/evidence.yaml`

---

## How to use

1. Open your agent at the **project root** (the directory you want audited and instrumented).
2. Paste everything under **"THE PROMPT"** verbatim.
3. The agent runs **Phase 0 (scope, read-only)** → **writes `audit/scope.yaml` and STOPS** → a human signs off by approving the scope hash → **Phase 1 (scaffold/reconcile)** → **Phase 2 (self-verify)**. The scope sign-off is an **enforced gate** (Phase 0.5), not a polite pause.

---

## THE PROMPT

You are bootstrapping a self-contained **audit gate** into THIS project. The gate is the last line of defense before deliverables reach high-IQ adversarial reviewers: any hole that ships is fatal, and the producer who fills in the findings is *not* a trusted party. Your job has two halves — **scope the project**, then **scaffold the gate** that grounds every future audit in real tool output and survives a motivated liar.

Operate from the project root. Write **no** harness files (other than the Phase-0 scope artifact) until the scope is approved. **Fail closed everywhere**: a required instrument that cannot run, parse, or cover a present surface caps the disposition at `HOLD`/`BLOCK` — never a silent pass. Bucket-D atoms are harness code, never prompts; a decidable-but-unimplemented atom is a `D-COVERAGE-GAP`, never reclassified as judgment.

### Phase 0 — identify and scope the project (READ-ONLY except the scope artifact)

Discover what this project actually is. Do not assume a layout. Enumerate, then classify, then report.

0. **Detect an existing harness first — update in place, never blindly re-scaffold.** Check whether `audit/` already contains a CRUCIBLE harness (`audit/audit.py` or the flat module set `models.py`/`recon.py`/`tools.py`/`policy.py`/`normalize.py`/`verifier.py`/`recall.py`/`cvss.py`, plus a drift ledger). If it does, this is an **UPDATE run**:
   - **Re-derive the scope** (steps 1–5) from the *current* tree and diff it against the existing `audit/scope.yaml`. New ecosystems/surfaces (a C/C++ tree, a Dockerfile, a multimodal dataset) the existing harness does not yet instrument become **newly-required instruments** and **new coverage gaps**.
   - **Preserve, do not discard:** keep the existing drift ledger, negative-control tests, custom `.crucible/semgrep` rules, and recorded waivers; *append* to them. Bump `REQUIRED_POLICY_VERSION` when the required-instrument set changes so old approvals re-trigger sign-off.
   - **Migrate, don't clobber:** add new tools to the registry, new parsers to `normalize.py`, new required-sets to `policy.py`, new rows to the drift ledger marked honestly (`Implemented` only with a passing test, else `Not implemented`/`D-COVERAGE-GAP`). Never delete a working gate to "start clean."
   - The update is itself **scope-gated**: a changed `required_instruments` set changes `scope.yaml`, which invalidates `scope.approved` and forces a fresh Phase-0.5 sign-off. Silently dropping a previously-required instrument is the starvation bypass and is forbidden.
   If `audit/` is absent, proceed as a fresh scaffold. Either way the rest of Phase 0 runs identically.

1. **Inventory the tree.** Walk the repo (respect `.gitignore`; skip `node_modules/`, `.venv/`, `venv/`, `dist/`, `build/`, `vendor/`, `.git/`, `__pycache__/`, `*.egg-info/`). Record top-level structure and every manifest/lockfile (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`, …). Record the git SHA and whether the working tree is dirty.

2. **Detect the deliverable surfaces.** For EACH, decide present/absent, list concrete paths, note structure. **Absence is a scoping result** — state it explicitly.
   - **Harness / runner code** — orchestrates agents, runs trials, scores rollouts, evaluates models.
   - **Agent trajectories** — recorded runs/transcripts (`*.jsonl`, `traces/`, ATIF-style files). Note schema and **where reward/score lives and who can write it**.
   - **Environment / dataset** — task defs, benchmark data, splits, fixtures. Note schema, splits, checksums/manifests, licensing.
   - **Client deliverables / artifacts** — generated reports, exports, built bundles, model outputs intended for a customer.
   - **Mock / synthetic data** — fixtures or seed data that could leak into a "real" deliverable.
   - **Rubrics / grading specs** — scoring criteria, verifier scripts, reward definitions. Note how reward is written and read.
   - **Test suite** — framework, config location, test dirs, markers.
   - **Docker / containers** — `Dockerfile*`, `docker-compose*`, devcontainers. Note base images, pinned-vs-floating tags. A built/shipped image is a contract-bearing surface.
   - **Git history** — the full commit history is a deliverable surface, not just the working tree (a deleted secret still ships in history; blobs bloat clones; a rewritten history breaks reproducibility). Record real-checkout (non-null SHA), shallow/truncated, dirty.

3. **Classify ecosystems & product types** from the manifests (Python/Node/Go/Rust/Java/other; monorepo/library/CLI/service/frontend/dataset/IaC/container). This drives which instruments apply.

4. **Derive the required-instrument set from the surfaces — do not let the producer choose it.** Each detected surface *mandates* its instruments (Python → ruff + bandit; dataset → schema + leakage + dedup; trajectory → schema + reward-provenance). A surface with no automated instrument becomes a **declared coverage gap**, never silence.

5. **Write the scope artifact and STOP.** Emit `audit/scope.yaml` — a machine-readable record of: project root, git SHA, dirty/clean, ecosystems, product types, the surface table (present/absent + paths + schema notes), the **derived `required_instruments` list**, the **scanner command/config policy** (each required tool's approved `argv` + config-file digests + ignore/exclude allow-list), the coverage-gap list, and an `ambiguities` field naming anything that needs human resolution. `scope.yaml` is the **single scope artifact** — do not also emit a human-readable scope document; the YAML is the machine format and the human reads it directly. **Do not proceed to Phase 1.**

### Phase 0.5 — the scope sign-off gate (ENFORCED, not advisory)

An autonomous agent does not reliably "stop and ask." Make the stop a hard precondition the scaffolder checks in code:

- A human (or out-of-band approver) reviews `audit/scope.yaml` and, if correct, writes its SHA-256 into `audit/scope.approved` (one line, the hex digest).
- The Phase-1 scaffolder's **first action** is to recompute `sha256(scope.yaml)` and compare it to `scope.approved`. If the file is missing or the digest differs, the scaffolder **raises and exits** — it does not write a single harness file.
- The approved digest binds both the **required-instrument set** and the **scanner command/config policy**: the recall gate (R1) reads `required_instruments` from the *approved* scope only, and command/config integrity (§1.10) compares each scanner's actual `argv`/config digests against the *approved* command/config policy. Re-scoping after approval — or quietly widening an ignore file — invalidates the digest and re-triggers sign-off. This defeats **required-set starvation** and **config starvation**.

### Phase 1 — scaffold or reconcile the audit gate (only after the scope digest matches)

Create a self-contained `audit/` project (uv, Python 3.12+) instrumenting THIS project — or, on an **UPDATE run**, *reconcile* the existing harness against the re-derived scope (add newly-required tools/parsers/required-sets, append drift-ledger rows, leave every still-passing gate and recorded waiver intact). Modules are flat and import each other by bare name (`from models import ...`); any new module must be added to the wheel `include` list and importable by `pytest` (via `conftest.py` on `sys.path` or `[tool.pytest.ini_options] pythonpath`).

> **The evidence bundle is committed; the raw transcripts are gitignored.** `audit/evidence.yaml` is **committed** — small enough to live in the tree, reviewable in a diff, and it carries every `run_id`, exit code, and stdout excerpt. What stays gitignored is `audit/results/` (the per-command `artifacts/CMD-NNN.stdout.txt` transcripts), because raw stdout is volatile, machine-specific, regenerated output. This does not weaken provenance: reproducibility comes from the **pinned inputs** (git SHA, scanner versions, pinned rule/DB digests, `scope.yaml` + `scope.approved`) plus the §1.10 signed artifact-closure manifest. For an immutable raw trail, sign the manifest and ship the artifacts to an append-only store — never trust stale raw artifacts from a different commit.

#### 1.1 Recon module
Capture git SHA, dirty state, timestamp, OS, network availability, runtime versions, repo roots + lockfiles, LOC by language, product types, and the Phase-0 surface map. **Record the pinned identity (version + digest) of every scanner's rule/vuln database** (see 1.3) so reproducibility is verifiable, not assumed.

#### 1.2 Instrument registry + runner (CRITICAL-capable, not just hygiene)
For each applicable tool: run it, capture the **real exit code**, write **full stdout/stderr to disk** (truncated excerpts are never the only record). Encode per-tool exit semantics (`nonzero != error` for many scanners). Record each run's status as a machine enum: `ok` · `nonzero_exit` · `timeout` · `tool_blocked`. Bound output volume (head+tail cap + gzip of the full stream).

Each `Tool` declares a **capability contract**, not just a binary name: `name, category, binary, build_argv, ecosystems, timeout_sec, required_when:list[str], critical_capable:bool, evidence_class:('static_reproducible'|'dynamic_live'|'heuristic'|'domain_integrity'), parser_required:bool, raw_artifact_required:bool, disposition_cap_on_absent:('HOLD'|'BLOCK')`. If a tool is `critical_capable` and its `required_when` matches the scoped repo, then a missing binary, a timeout, an unparsable artifact, or an uncovered present surface is a **coverage finding that caps the disposition**.

Required per matching surface (this is where CRITICAL recall lives): taint-aware SAST (CodeQL `security-extended` SARIF where buildable; Semgrep **explicit** packs `p/owasp-top-ten` + `p/r2c-security-audit` + `p/secrets` + `.crucible/semgrep` with `--metrics=off`, **never `--config auto`**; per-language source→sink taint rules + Harbor-domain rules: reward reads outside the verifier, agent-path reward writes, pass-rate-from-CSV-not-raw-trials, missing-reward-defaults-pass); per-language depth (`bandit`; `gosec`+`govulncheck`; `cargo audit`+`clippy`+`geiger`; `cppcheck`+`clang-tidy`+ASAN/UBSAN; `eslint`; `spotbugs`+find-sec-bugs); supply chain (`osv-scanner`, `pip-audit`, `npm/pnpm/yarn audit`, `cargo audit`, `govulncheck` — CVSS ≥ 9 / KEV / reachable-RCE floors `CRITICAL`); containers (`hadolint` + `trivy`); secrets (`gitleaks` over the working tree **and full history** `--log-opts=--all`); IaC/config/prose linters as surfaces demand. DAST (`nuclei`) and deep-ML similarity are **veto-only** (may cap `HOLD`/corroborate `BLOCK`, never support `SHIP`). The commodity hygiene tier (`ruff`, `ruff format`, `ty`, `radon`, `vulture`, `pytest`) is **necessary, never sufficient**.

#### 1.3 Pin scanner databases
Forbid `semgrep --config auto`. Record the snapshot version/digest of every DB-backed scanner in recon. An unpinned required DB caps the disposition at `HOLD`.

#### 1.4 Normalize + content-anchored multiset identity
`NormalizedIssue{tool, rule_id, severity(canonical 5), location_type(source|dependency|secret|config|artifact), path, line, package, version, vuln_id, advisory_id, tool_native_fingerprint, message, cluster_fingerprint, issue_instance_id}`. The **severity map is a hash-bound TOTAL function** (unknown native severity fails closed to ≥ `MEDIUM`, never `INFO`; a required-instrument finding is never mapped below `MEDIUM`). `cluster_fingerprint` **excludes the line number** (survives `ruff format`) = `sha256(canonical_tool, rule_id, subject, path_or_package, message_class_or_vuln_id, normalized_snippet)`. `issue_instance_id = sha256(cluster_fingerprint, occurrence_ordinal, source_manifest_digest, tool_id, rule_id)`. Identity is a **multiset**, not a set; the **verifier** computes both ids from raw output and the producer may only reference verifier-emitted ids; recall is per-instance. Parsing **fails closed** (a `parsed_ok=false` on a required tool caps `HOLD`). A hash-bound **CRITICAL floor** (injection / unsafe deserialization / SSRF / authz-bypass / secret exposure / memory corruption / CVSS ≥ 9 or KEV / container escape / dataset leakage / agent-writable reward / rollout miscount) cannot be waived to `SHIP`.

#### 1.5 Bespoke domain-integrity checks (THE CORE — deterministic, because no scanner ships them)
- `dataset_leakage_check` — exact SHA-256 + 256-perm MinHash over 5-token prose / 9-token code shingles + containment, across forbidden train/dev/ref/solution × test pairs. Exact-answer leak or Jaccard ≥ 0.85 / containment ≥ 0.80 → `CRITICAL` + `BLOCK`. Paraphrase heuristics are veto-only.
- `multimodal_dataset_leakage_check` — deterministic extractors (Pillow/ffprobe/libsndfile/pyarrow); Bucket-D fingerprints (image exact + pixel-SHA-256 + pHash/dHash/wHash + PDQ; audio PCM-SHA-256 + Chromaprint; video frame-hash + ffprobe). Near-dup thresholds, cross-modal media-id reuse, and answer-in-prompt/OCR/ASR leakage → `CRITICAL` + `BLOCK`. Embeddings/face/speaker are veto-only. Fail-closed coverage manifest.
- `reward_provenance_check` — reward must come from the verifier process only (hash-bound); the agent UID must not be able to write the reward path or modify verifier scripts/tests. Agent-writable reward → `CRITICAL` + `BLOCK`. Also schema + event-ordering + tool-call/result pairing + secret-leak.
- `rollout_integrity_check` — reconcile the expected matrix (job × task × agent × model × attempt × seed) against actual; recompute pass rates failing-by-default. Dropped/duplicated/miscounted rollout → `CRITICAL` + `BLOCK`.
- `report_claim_artifact_check` — parse the deliverables (`REPORT.md`, CSV/JSON, Markdown tables); recompute every quantitative claim from raw artifacts. A metric mismatch that changes a disposition → `CRITICAL` + `BLOCK`; an untraceable claim → `HIGH` + `HOLD`. Internal-data-consistency across `REPORT.md` vs a CSV vs a Markdown table vs the abstract/summary. Prose linters run as Bucket-D tool-runs; AI-slop tells (`TODO`/`_template`/`_example`/placeholder/lorem + repetitive-shingle filler) are veto-only.
- Container surface (`hadolint` + `trivy` + base-image digest) and git-history surface (`gitleaks` full history + blob + rewrite-anomaly) per scope.

#### 1.6 Emit the evidence bundle
A single machine-readable artifact (`audit/evidence.yaml`, committed) bundling recon + per-tool reports + run log + `normalized_issues[]` + `coverage_gaps[]` + not-run/blocked records. **This is the ONLY evidence source a downstream reviewer/LLM may cite.**

#### 1.7 Verifier — six deterministic rules
- **R1 recall** — per-instance verifier-owned ids; every ≥ `MEDIUM` issue from a parsed run must be acknowledged; an empty/all-clear report passes **only** if every required instrument ran clean and parsed; effective severity = **max over acknowledged** issues (not the producer's label); waiver discipline (reason-code enum + fingerprint-bound rationale + out-of-band approved waiver for HIGH/CRITICAL/security; boilerplate reused across unrelated fingerprints rejected).
- **R2 span resolution** — every `path:line` resolves against the Phase-1 source manifest (realpath inside the audit root, regular file, line in range; no `..`, no symlink escape).
- **R3 completed-run evidence** — only `ok`/`nonzero_exit` runs back a finding; `tool_blocked`/`timeout` back only a coverage gap. **R3-state**: `SHIP` requires non-null git SHA + clean tree + pinned DBs.
- **R4 CVSS form-vs-truth** — parse the full v3.1 vector, recompute the base score offline with a pinned calculator, reject any mismatched `cvss_base`; CWE format + registry membership are D, appropriateness is N.
- **R6 vocabulary** — dispositions `SHIP`/`HOLD`/`BLOCK` only; severity independent of disposition; tallies sum to the finding count.

#### 1.8 Orchestrator
One Typer app `audit/audit.py`, no bash wrapper, bootstrapped via `uv run --project audit audit all`. Four commands: **provision** (`uv sync --extra scanners`, hard-fail; native `osv-scanner`/`gitleaks`); **run** (recon + scanners + normalization → writes `audit/evidence.yaml` and the per-command stdout artifacts under `audit/results/`; Bucket-D evidence generation, *not* a gate); **verify** (the six rules against `findings.yaml`; exits `0` only when all hold — **the only command whose success means the gate passed**); **all** (provision unless `--no-install` → run → optional `--verify` → prints the Phase-2 hand-off; never writes findings; states that findings are **UNGATED until `audit verify` exits 0**). Per-tool timeouts + a global wall-clock budget.

#### 1.9 Negative-control tests
pytest fixtures proving each bypass is caught: (a) omitted issue/R1; (b) fabricated span (4 sub-cases)/R2; (c) blocked+timeout cited/R3; (d) empty all-`SHIP`/R1; (e) wrong `cvss_base` + missing CWE/R4; (f) dirty-tree + unpinned DB/R3-state. Plus a Hypothesis self-fuzz: the verifier never returns OK on an invariant violation and never crashes.

#### 1.10 Provenance gate (IMPLEMENTED — a required Bucket-D atom; `provenance.py`, wired into `verify_findings`)
A content-addressed artifact-closure manifest (`audit/provenance.manifest.yaml`, emitted by every `audit run`/`audit all`) covering the evidence digest, every citable source (path/realpath/sha256/line-count/type), git SHA + clean bit, every run's argv/cwd/status/exit-code + stdout-artifact digest, the policy version, and the scope + approved-scope digests. Phase 3 pre-checks run **before any other rule** (inside `verify_provenance`, fed into `verify_findings` as a disposition cap): **context integrity** (`sha256(audit/evidence.yaml)` matches the manifest — a post-run edit caps `BLOCK`); **scope integrity** (`sha256(scope.yaml)` still equals `scope.approved` and the manifest snapshot); **command/config integrity** (each run's live argv/cwd/status + stdout digest matches the manifest — argv swaps and artifact substitution cap `BLOCK`); **source integrity** (R2 resolves the *manifest snapshot*, closing TOCTOU; live source drift caps `SHIP`). **Trusted-Evidence Axiom**: a signature proves possession of a key, not honest collection, so `trusted` is **computed by the verifier, never copied** — `SHIP` requires a detached signature over the manifest's canonical bytes that verifies against a trust root supplied to the verifier from **outside the audited repo** (`AUDIT_TRUST_ROOT_KEY`, e.g. a CI/KMS secret the producer cannot mint) **and** a clean recorded tree (git SHA present, not dirty) **and** no source drift. Absent the external signature the run is self-attested and the disposition is capped at `HOLD`; a broken-integrity or unparsable manifest caps `BLOCK`; a missing manifest caps `HOLD`. On a producer-controlled host (no external key) `SHIP` is therefore mechanically unreachable — by design. Negative controls live in `audit/tests/test_provenance_negative_controls.py`.

#### 1.11 Generate the agent front doors
**The contract lives once in this file (`CRUCIBLE.md`, at the project root) and the run playbook lives once in `audit/README.md` — there is no `AUDIT.md`.** Every wrapper *defers* to `CRUCIBLE.md` and never re-states the contract; a wrapper that duplicates the axes, severity scale, or disposition vocabulary is a drift bug. Generate:

- `.opencode/command/audit.md` — YAML frontmatter (`description:` + `agent: build`); body: Phase 1 runs `!`​`uv run --project audit audit all -t 900`​`!`; Phase 2 reads `@REVIEW.md` as instructions and `@audit/evidence.yaml` as the ONLY source of instrumented evidence, then writes `findings.yaml` and `REPORT.md` at the project root (strip `_template`/`_example` keys; `REPORT.md` is the single human report — its **Bug Tickets** section carries the JIRA-style tickets); Phase 3 runs `uv run --project audit audit verify --findings findings.yaml --context audit/evidence.yaml`.
- `.opencode/skill/audit-gate/SKILL.md` — frontmatter `name: audit-gate` + a trigger `description`; body defers to `CRUCIBLE.md`, names the two artifacts (`findings.yaml` + `REPORT.md`), cites `audit/evidence.yaml`, and **never restates the contract**.
- An optional `.claude/commands/audit.md` (a one-screen wrapper that defers to `CRUCIBLE.md`); other tools take an equally thin wrapper pointing at the same source.

### Phase 2 — self-verify the scaffold

Prove the gate works before handing off: `ruff`/`ruff format`/type-check clean on the harness; `pytest` green including the negative-controls and self-fuzz; the scope sentinel refuses to scaffold on a missing/mismatched `scope.approved`; a real `audit run` produces `audit/evidence.yaml` with real exit codes; a `cluster_fingerprint` survives `ruff format`; a round-trip shows `audit verify` *fails* a broken `findings.yaml` and *passes* a correct one. Report the scaffold's coverage versus the detected surfaces, the remaining `D-COVERAGE-GAP`s, and the exact loop commands.

Then hand off: the model reads `REVIEW.md` + `audit/evidence.yaml`, writes `findings.yaml` + `REPORT.md` (the two artifacts), and the loop is `audit verify` until it exits `0`. The model touches only Phase 2; nothing the model does changes the contract.

---

## House rules (non-negotiable)

- **Root-canonical files** are `CRUCIBLE.md` (this prompt/contract) + `REVIEW.md` (the Phase-2 instruction prompt) + `findings.yaml` + `REPORT.md` (the reviewer artifacts). The committed evidence bundle is `audit/evidence.yaml`. **All** other harness code, research, docs, and the full rationale live under `audit/` (see `audit/README.md`); raw per-command transcripts live under `audit/results/` (gitignored). There is no `AUDIT.md`, no `BUGS.md` (folded into `REPORT.md`), and no `SCOPE.md`.
- **Provenance ≠ validity ≠ relevance.** The gate owns provenance, co-owns validity, and is mostly blind to relevance. A tool exiting `0` is a measurement under a configuration, not truth.
- **No invented evidence.** Every span resolves, every cited run completed, every CVSS recomputes. A fabricated span or a phantom/blocked run cited as proof is the first bug.
- **Absence is a result.** State every absent surface explicitly; never let silence read as safety.
- **Determinism over vibes.** Any atom specifiable as a total bounded recomputable relation is Bucket D (or a `D-COVERAGE-GAP`), never an LLM prompt. Total policies; unknowns fail closed.
- **Executable drift ledger.** Every Bucket-D guarantee needs an executable conformance test. An unimplemented guarantee is non-operative and caps the disposition; a row is marked `Implemented` only with a passing negative-control test. Editing this file and re-running reconciles the harness through the ledger — never silently.
