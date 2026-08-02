"""Per-pipeline options (the "kwargs" each pipeline accepts)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class _BaseOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PRRuntimeOptions(_BaseOptions):
    """Sandbox-verified PR mining: clones, applies diff, runs tests in bootstrap image.

    The pipeline runs each candidate PR's tests inside the bootstrap container
    twice — once with only `test_patch` applied (to capture which tests fail
    pre-fix), and once with both `test_patch` and the gold `patch` applied
    (to confirm which now pass). Tests that transition fail→pass become the
    `FAIL_TO_PASS` oracle; tests that pass both times become `PASS_TO_PASS`
    regression guards. See docs/pipelines/pr_runtime.md.
    """

    # --- Mining (mirrors PRDiffOptions where overlap exists) ---
    limit: int = 50
    since: date | None = None
    until: date | None = None
    state: Literal["merged"] = "merged"
    skip_drafts: bool = True
    require_linked_issue: bool = True
    languages: list[str] = ["python"]

    # --- Validation ---
    require_fail_to_pass: bool = True  # skip PRs whose F2P set is empty after validation
    min_fail_to_pass: int = 1
    validation_timeout_sec: int = 600  # per-PR cap on the two test runs
    skip_validation: bool = False  # emit candidates without F2P/P2P (debug / fast iteration)

    # --- Quality (SWE-bench Lite-style sampling) ---
    lite_filter: bool = False
    max_source_files_per_pr: int = 50  # PRs touching >N source files are excluded
    min_problem_statement_words: int = 0  # Lite ≈ 40

    # --- Structural filters (cheap, applied before validation) ---
    require_new_test_funcs: bool = True  # test_patch must add ≥1 new test func/class
    skip_ci_only: bool = True  # auto-skip when source patch is 100% under .github/


class PRDiffOptions(_BaseOptions):
    """SWE-RL-style PR mining with a Harbor-runnable diff-similarity verifier.

    Each emitted task includes an environment/Dockerfile (python:3.12-slim +
    git + the repo checked out at base_commit + the oracle diff baked in)
    and a tests/test.sh that captures the agent's edits via `git diff` and
    scores them against the oracle using SWE-RL-style sequence similarity
    (mirrors `repo2rlenv.reward.calculate_diff_similarity_reward`). The
    Dockerfile is intentionally minimal — no LLM bootstrap — so cells stay
    cheap.
    """

    limit: int = 50
    since: date | None = None
    until: date | None = None
    state: Literal["merged", "all"] = "merged"
    context_window_loc: int = 200
    diff_format: Literal["unified", "search_replace"] = "unified"
    max_files_per_pr: int = 5
    skip_drafts: bool = True
    # Emit environment/Dockerfile + tests/test.sh so the task is a fully
    # Harbor-runnable env. Default on. Set False to fall back to the
    # v0.8.1 text-only output (just instruction.md + solution/patch.diff)
    # for training pipelines that compute the reward externally.
    emit_harbor_env: bool = True
    # Minimum number of +/- lines in the oracle diff to accept as a task.
    # Below this is too trivial to be a meaningful RL signal — typically
    # a one-character typo fix or a doc tweak.
    min_loc_changed: int = 3


class CommitRuntimeOptions(_BaseOptions):
    """Commit-level mining (R2E-Gym SWE-GEN style).

    Walks `git log` instead of `gh pr list`. Same validation harness as
    `pr_runtime` once we have a (patch, test_patch, base_commit) tuple.
    Commits are noisier than PRs — we filter aggressively at the file +
    message level before running the (expensive) validation harness.
    """

    # --- Mining ---
    limit: int = 50
    since: date | None = None
    until: date | None = None
    branch: str = "HEAD"
    clone_depth: int = 200  # deeper than bootstrap's depth=1 so git log can walk

    # --- Filters (cheap, applied before validation) ---
    skip_merge_commits: bool = True
    min_message_words: int = 5  # drop "wip", "fmt", "typo" etc.
    max_source_files_per_commit: int = 10
    exclude_authors: list[str] = []  # e.g. ["dependabot[bot]@users.noreply.github.com"]
    require_new_test_funcs: bool = True  # test_patch must add ≥1 new test func
    skip_ci_only: bool = True

    # --- Validation (mirrors PRRuntimeOptions) ---
    require_fail_to_pass: bool = True
    min_fail_to_pass: int = 1
    validation_timeout_sec: int = 600
    skip_validation: bool = False

    # --- Instruction synthesis ---
    synthesize_with_llm: bool = False  # if False, use raw commit subject + body
    min_problem_statement_words: int = 0


class MutationBugsOptions(_BaseOptions):
    """SWE-smith-style synthetic bug injection.

    Picks Python source files in the target repo, applies an AST mutation
    operator (flip_comparison / off_by_one / swap_arithmetic / ...), runs
    the existing test suite, and accepts the mutation if it breaks between
    `min_tests_broken` and `max_tests_broken` tests.

    The "fix" the agent must produce is the inverse mutation; the oracle
    is the original (pre-mutation) source. See docs/pipelines/mutation_bugs.md.
    """

    # --- Discovery ---
    limit: int = 50
    file_glob: str = "**/*.py"
    exclude_glob: list[str] = [
        "tests/**",
        "test_**",
        "**/test_*.py",
        "**/*_test.py",
        "**/conftest.py",
        "**/setup.py",
        "docs/**",
        "examples/**",
        "**/__init__.py",  # mutating __init__ tends to break imports catastrophically
    ]

    # --- Operators ---
    operators: list[str] | None = None  # None ⇒ use every default operator
    seed: int | None = None  # RNG seed for reproducibility (None ⇒ time-based)
    max_attempts_per_file: int = 5  # give up on a file if it refuses to mutate productively

    # --- Mutation filter ---
    min_tests_broken: int = 1
    max_tests_broken: int = 5
    validation_timeout_sec: int = 300
    skip_validation: bool = False  # emit candidates raw (debug / fast iteration)
    # If set, restrict pytest to this path (or space-separated list of paths).
    # Lets fast iteration scope to one test file (e.g. `tests/test_basic.py`)
    # instead of running the whole suite per mutation candidate. The emitted
    # task's verifier still uses the targeted file list derived from the
    # specific broken tests, so this only affects the GENERATION-TIME scan.
    test_target: str | None = None

    # --- LLM ---
    llm_temperature: float = 0.7
    max_llm_tokens: int = 1024


class CodeInstructOptions(_BaseOptions):
    """Magicoder-OSS-Instruct-style, anchored to a target repo + verified by execution.

    Samples a seed snippet from the repo, asks the LLM for a self-contained
    coding task (problem statement + pytest test + oracle solution), then
    verifies in the bootstrap container: the test must FAIL on HEAD and PASS
    once the oracle solution is applied. Failures are skipped.

    See docs/pipelines/code_instruct.md.
    """

    # --- Sampling ---
    limit: int = 50
    seed_min_loc: int = 30
    seed_max_loc: int = 200
    file_glob: str = "**/*.py"
    exclude_glob: list[str] = [
        "tests/**",
        "test_**",
        "**/test_*.py",
        "**/*_test.py",
        "docs/**",
        "examples/**",
        "**/__init__.py",
    ]
    seed: int | None = None
    max_attempts_per_seed: int = 1

    # --- LLM ---
    llm_temperature: float = 0.7
    max_llm_tokens: int = 2048

    # --- Verification ---
    require_test_fails_without_oracle: bool = True
    require_test_passes_with_oracle: bool = True
    validation_timeout_sec: int = 180
    skip_validation: bool = False

    # --- Decontamination ---
    skip_decontamination: bool = False

    # --- Cost cap (mirrors BootstrapSpec.max_llm_spend_usd) ---
    # When set, the candidate loop short-circuits once accumulated LiteLLM cost
    # crosses this ceiling. None = unbounded.
    max_llm_spend_usd: float | None = None

    # --- AWS mode ---
    aws_mode: bool = False

    # --- cli_app mode (build full CLI app from a target repo) ---
    # When mode == "cli_app", the snippet-mode fields above (sampling, LLM
    # temperature, decontam) are largely ignored. The pipeline AST-extracts
    # a CLI spec + per-test intents from the target repo, LLM-translates
    # intents into black-box tests, synthesises an oracle, and emits a
    # Harbor-format RL environment. Orthogonal to `aws_mode` (snippet+AWS).
    # See docs/AWS_CLI_S3_PLAN.md (v3).
    mode: Literal["snippet", "cli_app"] = "snippet"
    cli_app_command_prefix: str = ""  # e.g. "s3" for aws s3 *
    cli_app_command: str | None = None  # focus on one command (None = all)
    cli_app_entry_point_override: str | None = None
    cli_app_tests_dir_override: str | None = None
    cli_app_max_intents: int = 10  # cap on per-run translation calls
    cli_app_skip_gauntlet: bool = False  # skip G1-G4 (for smoke runs)
    cli_app_skip_suite_verify: bool = False  # skip Docker suite-level verify
    cli_app_translation_model: str | None = None  # override --llm for translation
    cli_app_per_intent: bool = False  # emit one task per (command, intent) instead of per command
    # Default ON: gate every real generation (golden-cert / G3+G4) so bad tasks are
    # rejected rather than self-certified. Skips gracefully when Docker is unavailable,
    # where honest metadata (discriminative=False) marks the task unverified instead.
    cli_app_docker_gauntlet: bool = True
    cli_app_docker_empty_pass_max: float = 0.05  # G3 reject threshold: empty stub must pass <= 5%
    cli_app_docker_oracle_pass_min: float = 1.0  # G4 reject threshold: oracle must pass 100%
    cli_app_docker_timeout_sec: int = 480  # per-run pytest timeout inside container; 480s accommodates ~30s kwokctl cluster startup on the two gauntlet runs plus real pytest time
    # --- cli_app subset (multi-command) tasks ---
    # When set, emit ONE task per compatible subset of commands (instead of one
    # task per command). Each entry is a comma-joined command list, e.g.
    # ["mb,ls,rb", "mb,cp,ls,rm"]. None = unchanged per-command behaviour.
    cli_app_subsets: list[str] | None = None
    # Auto-enumerate command SUBSETS from the discovered surface and sample by
    # difficulty tier, instead of requiring an explicit cli_app_subsets list. Applies
    # ONLY to generic sidecar backends (never dynamodb_local / minio). Ignored when
    # cli_app_subsets is set.
    cli_app_auto_subsets: bool = True
    # Cap on auto-generated subsets (0 = unbounded); sampled hardest-first.
    cli_app_max_subsets: int = 24
    # Difficulty tiers to include when auto-sampling subsets (None = all tiers).
    cli_app_subset_tiers: list[str] | None = None
    # --- Coverage matrix (service-agnostic; generic sidecar backends only) ---
    # Expand each command into a service-model-derived scenario matrix: pairwise
    # optional-flag combinations, enum-value coverage, and numeric/length boundary
    # values -- the automatic substitute for hand-authored edge cases, giving a new
    # service edge/boundary depth. Applies ONLY to generic backends; dynamodb_local
    # and minio intents are unchanged. Default ON.
    cli_app_combinations: bool = True
    # Cap on pairwise optional-flag combinations per command (the required-only
    # happy path is always emitted regardless of this cap).
    cli_app_max_optional_combos: int = 6
    # Mutually-exclusive flag groups for conflict-case generation, each a comma-
    # joined group that must not co-occur (e.g. "--billing-mode,--provisioned-throughput").
    # None = no conflict cases. Service-agnostic; declare per service/feature.
    cli_app_mutually_exclusive: list[str] | None = None
    # Number of cross-command workflow tests to synthesise per subset task
    # (0 disables). Ignored for single-command tasks.
    cli_app_workflow_tests: int = 3
    # Number of parallel LLM worker threads for per-intent test translation.
    # Each intent is a self-contained LLM call; 1 = strictly sequential (safe
    # default for rate-limited providers). Bumping to 4-8 gives ~4-6x wall-time
    # speedup with the same total token spend on providers that permit
    # concurrent requests.
    cli_app_translate_workers: int = 1
    # --- Reference grounding (real aws-cli as ground-truth oracle) ---
    # When True, the Docker gauntlet keeps ONLY tests that BOTH the real `aws`
    # CLI AND the synthesised oracle pass, and that an empty stub fails. This
    # removes LLM-hallucinated/brittle tests and guarantees the gold patch
    # solves its own task. Requires Docker. The `aws` binary lives only in the
    # gauntlet image, never in the shipped task image (anti-cheat).
    cli_app_reference_grounding: bool = False
    # Reject a task if fewer than this many tests survive reference grounding.
    cli_app_min_grounded_tests: int = 3
    cli_app_min_tests_final: int = 0
    cli_app_min_happy_path: int = 0
    cli_app_min_error_nonexistent: int = 0
    cli_app_min_error_invalid_args: int = 0
    cli_app_min_workflow: int = 0
    cli_app_min_edge: int = 0
    # Anti-reward-hacking AST scan of the synthesised oracle. Tri-state: None = auto
    # ("reject" for generic sidecar backends; "log"-only for the byte-locked
    # dynamodb_local / minio so they are scanned for telemetry but never rejected);
    # "off" disables. Resolved by _effective_antihack_mode().
    cli_app_antihack_scan: Literal["off", "log", "reject"] | None = None
    cli_app_ecr_push: bool = False
    cli_app_ecr_registry: str | None = None
    cli_app_ecr_profile: str | None = None
    cli_app_platforms: list[str] | None = None
    # Override the app Dockerfile's BASE_IMAGE (the baked polyglot base). None =
    # the pipeline default (repo2rlenv.pipelines._cli_app_synthesis.PINNED_BASE_IMAGE).
    cli_app_base_image: str | None = None
    # --- cli_app backend + extraction mode (S3/MinIO defaults; DynamoDB opt-in) ---
    # Which simulation backend the emitted task boots -- the key of a registered
    # ServiceProfile. "minio" (S3, byte-identical output) and "dynamodb_local"
    # (in-container DynamoDB Local JVM + stdlib raw-HTTP client) ship built-in; any
    # newly registered profile is selectable. A plain str (not Literal) so adding a
    # service needs no options edit; validated against the registry at pipeline runtime.
    cli_app_backend: str = "minio"
    # How the command surface is extracted. "tests" derives commands from
    # aws-cli `test_<cmd>_command.py` filenames (the S3 path). "botocore_model"
    # reads the vendored `botocore/data/<service>/*/service-2.json` off disk and
    # synthesises intents from the request/response shapes (required for
    # `aws dynamodb`, whose verbs are model-generated, not an awscli customization).
    cli_app_extract_mode: Literal["tests", "botocore_model"] = "tests"
    # Absolute path escape hatch to a service-2.json (or a botocore data dir) when
    # the extractor cannot locate the model inside the clone. None = auto-detect.
    cli_app_service_model_override: str | None = None
    # Absolute path escape hatch to a kubectl YAML bundle (kwok backend only).
    # None = auto-locate at envs/<owner>_<repo>/kubectl_spec.yaml (built by the
    # C4 Go extractor at pipelines/_cli_app_backends/source/cobra_extractor/).
    cli_app_kubectl_yaml_bundle_path: str | None = None
    # Absolute path escape hatch to a directory of hand-authored kubectl pytest
    # fixtures (test_kubectl_<verb>_<behaviour>_NN.py + test_kubectl_workflow_*.py
    # + conftest.py). Kwok backend only. When set and every command in the subset
    # has fixture coverage, the LLM-synthesised tests + gauntlet + reference
    # grounding are skipped and the fixture files ship verbatim. Missing verb
    # coverage falls back to the LLM path unchanged.
    cli_app_kubectl_fixture_dir: str | None = None
    # Cap on shipped fixture tests per task; kwok backend only, applied after the
    # workflow relevance filter. None = ship every matched fixture. Sampling is
    # stratified by (verb, behaviour-tag) and deterministic across reruns via a
    # sha256 seed of the sorted subset commas.
    cli_app_kubectl_fixture_max_tests: int | None = None
    # Kubernetes kinds subset for kwok tasks. When set, fixture selection filters
    # by (verb, kind) using tests/fixtures/kubectl_testcases/kind_index.json;
    # uncovered (verb, kind) pairs fall back to LLM synthesis. None = kind-agnostic.
    cli_app_kubectl_kinds: list[str] | None = None
    # CamelCase operation names to lift in botocore_model mode. None = the 8
    # default DynamoDB pilot verbs (see _cli_app_extract._DDB_TARGET_OPS_DEFAULT).
    cli_app_target_operations: list[str] | None = None
    # Auto-scope cap: when a generic sidecar profile declares NO default_target_ops
    # and discovers more commands than this, narrow to a coherent lifecycle subset
    # via select_lifecycle_scope(). 0 disables. Never applies to dynamodb_local /
    # minio (byte-locked) nor to a profile that curated its own default_target_ops.
    cli_app_scope_max_commands: int = 7
    # Oracle strategy. "both" (default) ships BOTH a deterministic real-aws-cli golden
    # slice (awscli + botocore + s3transfer static-import closure + service data, verbatim
    # as solution/golden.diff) AND the LLM-synthesised solution/reference.diff, for every
    # service. "golden" ships only the slice; "llm" opts out to the LLM oracle alone
    # (offline / no-Docker / cheap runs). golden/both require source_root (the cloned
    # aws-cli checkout); a slice failure hard-rejects the task rather than shipping an LLM golden.
    cli_app_oracle: Literal["llm", "golden", "both"] = "both"
    # Max output tokens for the reference-oracle LLM call. Kubectl kwok
    # 8-verb x 14-kind subsets need ~1800 lines (~30k tokens); the previous
    # 16000 ceiling silently truncated main.py mid-function, dropping the
    # __main__ dispatcher and half the verb handlers.
    cli_app_oracle_max_tokens: int = 32000
    # Retries on transient oracle-synth failures (SyntaxError from truncation,
    # LLM refusal, provider hiccup). 1 = no retry (original behaviour). The
    # LLM output cache is bypassed per attempt so we get a fresh sample.
    cli_app_oracle_max_attempts: int = 3
    # When True, synthesise the reference oracle command-by-command rather than
    # in a single LLM call; used by the kwok kubectl backend to keep per-call
    # output bounded on large subsets.
    cli_app_oracle_split_by_command: bool = False

    # --- Team-guarantee knobs: >=100 real-aws-grounded, zero-skip, >=6-command tasks ---
    # Generic sidecar backends only. The byte-locked minio / dynamodb_local paths never
    # reach the auto-subset / top-up / refinement code (all gated on _is_generic_backend),
    # so every field below is inert for them and cannot perturb their locked output.
    #
    # Auto-subset command-count window, threaded into sample_subsets (generic backends).
    cli_app_subset_min_commands: int = 6
    cli_app_subset_max_commands: int = 11
    # Hard floor on grounded tests per emitted task (0 = disabled). The top-up loop drives
    # toward this; still below it after the loop -> _TaskRejected. Generic path only.
    cli_app_min_grounded_final: int = 0
    # Per-service overrides for the floor, e.g. {"local_kms": 100}; wins over the global.
    cli_app_min_grounded_final_overrides: dict[str, int] = {}
    # Top-up loop budget per subset task (0 attempts = loop disabled). First cap hit stops.
    cli_app_topup_max_attempts: int = 0
    cli_app_topup_max_cost_usd: float | None = None
    cli_app_topup_max_wall_sec: int | None = None
    # G5: enrich the pinned aws-cli 2.28.23 model's shapes (enum / error-code / example
    # values) from other aws-cli model versions. NEVER adds new ops/flags (they would fail
    # 2.28.23 reference grounding). Opt-in.
    cli_app_multi_version_enrichment: bool = False
    # Zero-skip guarantee: reject shipped tests containing pytest.skip / skipif / xfail.
    cli_app_forbid_skips: bool = False

    # --- In-pipeline dynamic validation gate (kwok backend only) ---
    # Runs pytest inside the freshly built task image against the golden slice,
    # the LLM reference, and an empty stub, then applies pass/fail thresholds
    # before shipping. Inert for minio/dynamodb_local (they use the static
    # docker-gauntlet path above).
    cli_app_validation_gate: bool = True
    cli_app_validation_timeout_sec: int = 300
    cli_app_validation_min_golden_reward: float = 0.99
    cli_app_validation_max_empty_reward: float = 0.05
    cli_app_validation_min_reference_reward: float = 0.5
    cli_app_validation_gate_required: bool = False
    cli_app_validation_gate_compile: bool = True
    cli_app_validation_gate_compile_timeout_sec: int = 600

    @model_validator(mode="after")
    def _validate_aws_mode_backend(self) -> CodeInstructOptions:
        if self.aws_mode and self.cli_app_backend not in {"minio", "dynamodb_local"}:
            raise ValueError(
                f"aws_mode=True requires cli_app_backend in {{'minio', 'dynamodb_local'}}, "
                f"got {self.cli_app_backend!r}"
            )
        return self


class RefactorSynthesisOptions(_BaseOptions):
    """Mine historical rename refactors from commit history.

    Two-stage detection:
      1. Commit message regex matches a "rename X to Y" phrase
      2. Diff verification: old token removed, new token added, no
         surviving `def OLD(...)` / `class OLD ...` definition

    Emitted task = "rename X to Y throughout the codebase"; verifier
    checks both behavioral (tests still pass) and structural (old name
    gone, new name present) criteria.

    See docs/pipelines/refactor_synthesis.md.
    """

    # --- Mining ---
    limit: int = 50
    since: date | None = None
    until: date | None = None
    branch: str = "HEAD"
    clone_depth: int = 200  # deeper than bootstrap's depth=1 so git log walks

    # --- Metadata filters ---
    skip_merge_commits: bool = True
    exclude_authors: list[str] = []

    # --- Verification ---
    # Default False because real-world Python renames in mature libs keep a
    # back-compat shim using the old name. Set True for stricter "old name
    # must be fully removed" semantics (will reject most public-API renames).
    require_old_name_gone: bool = False
    require_new_name_present: bool = True
    validation_timeout_sec: int = 300
    skip_validation: bool = False


class CVEPatchesOptions(_BaseOptions):
    """Map OSV vulnerability records to fixing commits in the target repo.

    For each vuln returned by OSV's `/v1/query`, find a `references[]` URL
    pointing at `github.com/<owner>/<repo>/commit/<sha>`, fetch that
    commit's diff, split into source/test patches, and emit a Harbor task
    whose verifier mirrors `commit_runtime` (F2P/P2P validation when a
    test_patch is present; emission-only otherwise).

    See docs/pipelines/cve_patches.md.
    """

    # --- OSV discovery ---
    osv_ecosystem: str | None = None  # "PyPI" / "npm" / "crates.io" / ... (None ⇒ auto-guess)
    osv_package: str | None = None  # package name (None ⇒ use repo name)
    min_severity: Literal["low", "medium", "moderate", "high", "critical"] = "low"

    # --- Output cap ---
    limit: int = 50

    # --- Validation (mirrors PRRuntimeOptions) ---
    require_fail_to_pass: bool = False  # CVE fixes often have no test_patch — accept anyway
    min_fail_to_pass: int = 0
    validation_timeout_sec: int = 600
    skip_validation: bool = False

    # --- Structural filters ---
    require_new_test_funcs: bool = False  # security commits often DON'T add new tests
    max_source_files_per_fix: int = 50


class EquivalenceTestsOptions(_BaseOptions):
    """R2E-style function-level equivalence-test synthesis.

    Extracts module-level Python functions from the target repo, asks the
    LLM to write a pytest test that calls both `<name>` (candidate, stubbed
    in env) and `reference_<name>` (frozen oracle) with crafted inputs and
    asserts outputs match. Verifies in-sandbox: the test must FAIL when
    `<name>` is stubbed and PASS when `<name>` is the original.

    See docs/pipelines/equivalence_tests.md.
    """

    # --- Discovery ---
    limit: int = 50
    min_loc: int = 5  # min lines in function body
    max_loc: int = 60  # max lines in function body
    file_glob: str = "**/*.py"
    exclude_glob: list[str] = [
        "tests/**",
        "test_**",
        "**/test_*.py",
        "**/*_test.py",
        "**/conftest.py",
        "docs/**",
        "examples/**",
        "**/__init__.py",
        "**/setup.py",
    ]
    seed: int | None = None
    max_attempts_per_function: int = 1

    # --- LLM ---
    llm_temperature: float = 0.5  # lower than code_instruct — we want stable tests
    max_llm_tokens: int = 1500

    # --- Verification ---
    require_test_fails_with_stub: bool = True
    require_test_passes_with_oracle: bool = True
    validation_timeout_sec: int = 90
    skip_validation: bool = False


class PerfRuntimeOptions(_BaseOptions):
    """Corpus-driven performance optimization tasks.

    The harvest stage is solved upstream, so this pipeline reads records rather than
    scraping. Each record carries the base commit, the reference optimization, the
    covering tests, the timed workload, and the measured expert speedup.
    """

    corpus: str = "harvest"           # directory of *.jsonl, or a single file
    repos: list[str] = []             # restrict to these repos; empty means all
    instances: list[str] = []         # restrict to these instance ids; empty means all
    limit: int = 0                    # 0 means every admissible record
    skip_image_build: bool = False    # emit bundles without building images
    build_timeout_sec: int = 3600
    skip_calibration: bool = False    # emit without measuring the oracle first
    calibration_timeout_sec: int = 1800
    # A task ships only when the oracle gain exceeds this multiple of its own
    # measurement noise, so the target is separable from the host rather than
    # merely larger than it.
    discrimination_margin: float = 2.0
    stability_trials: int = 3
    max_environment_repairs: int = 4
    max_void_retries: int = 4


OPTIONS_REGISTRY: dict[str, type[_BaseOptions]] = {
    "perf_runtime": PerfRuntimeOptions,
    "pr_runtime": PRRuntimeOptions,
    "pr_diff": PRDiffOptions,
    "commit_runtime": CommitRuntimeOptions,
    "mutation_bugs": MutationBugsOptions,
    "code_instruct": CodeInstructOptions,
    "equivalence_tests": EquivalenceTestsOptions,
    "cve_patches": CVEPatchesOptions,
    "refactor_synthesis": RefactorSynthesisOptions,
}


def parse_options(pipeline_name: str, raw: dict) -> _BaseOptions:
    cls = OPTIONS_REGISTRY.get(pipeline_name)
    if cls is None:
        raise ValueError(
            f"pipeline {pipeline_name!r} has no Options registered "
            f"(known: {sorted(OPTIONS_REGISTRY)})"
        )
    return cls.model_validate(raw)
