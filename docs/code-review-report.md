# Hostile Code Review: SWE-fficiency Report Files

**Files Under Review:**
1. `swefficiency/report.py` (283 lines) — canonical report module, imported by CLI
2. `scripts/eval/get_report.py` (233 lines) — standalone script, older version
3. `scripts/eval/get_lite_report.py` (237 lines) — standalone script, lite dataset variant

---

## 1. CONTRADICTIONS & LOGICAL IMPOSSIBILITIES

```
[SEVERITY: CRITICAL]
[CATEGORY: Contradiction]
[LOCATION: report.py:106,157 — two different patch_length calculations in SAME function]
FINDING: Same function returns two different patch_length metrics depending on code path
EVIDENCE:
  Line 106: num_modified_lines = get_number_of_patch_modified_lines(instance["patch"])
            (counts only +/- lines, excluding headers — the semantic diff size)
  Line 120: "patch_length": num_modified_lines (early return path — uses modified lines)
  Line 157: "patch_length": len(instance["patch"].splitlines()) (normal return path — counts ALL lines including context, headers, hunks)
SCENARIO: Instance A takes early return (no correctness dir), Instance B takes normal path.
  Both report "patch_length" but with incompatible semantics. A 50-line patch with 10 modified
  lines reports patch_length=10 via early return, patch_length=50 via normal return.
IMPACT: Any analysis comparing patch_length across instances is INVALID. Regression models,
  correlations, normalizations — all corrupt. This is in the benchmark's PRIMARY output metric.
FIX: Use one metric consistently. Line 157 should be "patch_length": num_modified_lines.
```

```
[SEVERITY: CRITICAL]
[CATEGORY: Contradiction]
[LOCATION: report.py:283 vs function signature at line 228]
FINDING: generate_report() return type is not declared and returns a bare tuple, not pd.DataFrame
EVIDENCE:
  Signature: def generate_report(...) -> pd.DataFrame (line 228, docstring says "Returns: DataFrame")
  Actual return: return results_df, breakdown, csv_path, json_path (line 283 — a 4-tuple)
  Caller: cli.py:160: _, breakdown, csv_path, json_path = generate_report(...) (expects 4-tuple)
SCENARIO: Any caller that trusts the type annotation and writes df = generate_report(...) gets
  a tuple, not a DataFrame. df.columns -> AttributeError.
IMPACT: Type annotation is a lie. IDE autocompletion, type checkers, and future callers are misled.
FIX: Change annotation to -> tuple[pd.DataFrame, Dict, Path, Path] or return a named dataclass.
```

```
[SEVERITY: HIGH]
[CATEGORY: Contradiction]
[LOCATION: report.py:102 vs get_report.py:83-105]
FINDING: report.py sets gold_perf_info fallback but get_report.py doesn't — divergent error behavior
EVIDENCE:
  report.py:102: gold_perf_info = {"before_mean": 0.0} (fallback when gold run doesn't exist)
  get_report.py:83: gold_speedup_ratio = 1.0 (NO gold_perf_info fallback)
  get_report.py:105: "pre_edit_runtime": gold_perf_info["before_mean"] <- WILL CRASH:
    NameError because gold_perf_info was never assigned in the else branch
SCENARIO: Gold run doesn't exist for an instance. get_report.py:105 references undefined gold_perf_info.
IMPACT: get_report.py crashes with NameError on any instance missing a gold run. report.py survives
  with 0.0 fallback. The two files that should produce identical results behave completely differently.
FIX: Add gold_perf_info = {"before_mean": 0.0} to the else branch in get_report.py line 83.
```

```
[SEVERITY: HIGH]
[CATEGORY: Contradiction]
[LOCATION: report.py vs get_report.py — early return dict keys differ]
FINDING: report.py early return includes raw_pred_speedup_ratio, get_report.py does not
EVIDENCE:
  report.py:111: returns "raw_pred_speedup_ratio": 1.0 in early return path
  get_report.py:96-107: early return dict has NO raw_pred_speedup_ratio key
  Both files' normal return path (report.py:144, get_report.py:142) include raw_pred_speedup_ratio
SCENARIO: get_report.py's early return produces rows missing raw_pred_speedup_ratio.
  When loaded into a DataFrame, these rows have NaN for that column.
IMPACT: Any downstream analysis on raw_pred_speedup_ratio gets NaN contamination. Harmonic mean
  calculation would produce NaN if this column were used.
FIX: Add "raw_pred_speedup_ratio": 1.0 to get_report.py's early return dict (line 96-107).
```

```
[SEVERITY: HIGH]
[CATEGORY: Contradiction]
[LOCATION: report.py:79-80 vs get_report.py:62]
FINDING: report.py handles pass_to_pass as string (JSON-encoded), get_report.py does not
EVIDENCE:
  report.py:79-80:
    if isinstance(pass_to_pass, str): pass_to_pass = json.loads(pass_to_pass)
  get_report.py:62:
    pass_to_pass = instance["PASS_TO_PASS"] — no string handling
SCENARIO: If PASS_TO_PASS is stored as a JSON string in the dataset (common with HuggingFace),
  report.py correctly deserializes it. get_report.py tries to iterate over a string character by
  character — for test in '["test_foo"]' iterates over [, ", t, e...
IMPACT: get_report.py produces wrong correctness metrics for every instance when PASS_TO_PASS
  is JSON-encoded. ALL evaluation results from get_report.py are wrong in this scenario.
FIX: Add the same isinstance check to get_report.py.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Contradiction]
[LOCATION: report.py:141 vs get_report.py:128]
FINDING: Vacuous truth — empty pass_to_pass = 100% correctness
EVIDENCE: correctness_pct = len(passed_tests) / len(pass_to_pass) if pass_to_pass else 1.0
SCENARIO: Instance with no pass-to-pass tests gets correctness = 1.0 -> speedup ratio is NOT
  penalized -> inflated benchmark scores for instances with no test coverage
IMPACT: Benchmark scores inflated for poorly-covered instances.
FIX: Return 0.0 or explicitly flag as "ungraded" when pass_to_pass is empty.
```

---

## 2. FAILURE MODE ANALYSIS

```
[SEVERITY: CRITICAL]
[CATEGORY: Failure Mode]
[LOCATION: report.py:36-39, get_report.py:31-34]
FINDING: parse_perf_summary() crashes on malformed perf_summary.txt with no error handling
EVIDENCE:
  before_mean = float(perf_lines[0].split(":")[1].strip())
  No try/except. No validation of line count or format.
SCENARIO: perf_summary.txt is empty, has fewer than 4 lines, has a line without ":",
  or has non-numeric values. IndexError, ValueError, or ZeroDivisionError.
IMPACT: One corrupted perf_summary.txt crashes the ENTIRE report generation for ALL instances
  (multiprocessing.Pool worker dies, pool.imap hangs or raises).
FIX: Wrap in try/except, return None or a sentinel. Filter out failed parses upstream.
```

```
[SEVERITY: HIGH]
[CATEGORY: Failure Mode]
[LOCATION: report.py:89, get_report.py:71]
FINDING: Division by zero when after_mean is 0
EVIDENCE: pred_speedup_ratio = pred_perf_info["before_mean"] / pred_perf_info["after_mean"]
SCENARIO: Benchmark runs in 0.0 seconds (e.g., trivial test, or perf tool reports 0).
  Division by zero -> ZeroDivisionError -> worker crash -> pool crash.
IMPACT: One edge-case instance kills the entire report.
FIX: Guard with max(after_mean, 1e-9) or handle ZeroDivisionError explicitly.
```

```
[SEVERITY: HIGH]
[CATEGORY: Failure Mode]
[LOCATION: get_report.py:183-184, get_lite_report.py:187-188]
FINDING: Harmonic mean crashes when ANY human_speedup_ratio is 0
EVIDENCE:
  harmonic_mean_human_speedup = len(results_df) / (1 / results_df["human_speedup_ratio"]).sum()
  When human_speedup_ratio = 0: 1/0 -> inf -> sum is inf -> N/inf -> 0.0 (or NaN depending on pandas).
  BUT: When gold_speedup_ratio=0, the code sets human_speedup_ratio=0 (report.py:152, get_report.py:150).
  So 1/0 actually produces inf in pandas, and sum of inf = inf, so result = 0.0. Misleading but not crash.
  HOWEVER: If human_speedup_ratio contains NaN (from the missing raw_pred_speedup_ratio bug above),
  1/NaN = NaN, sum = NaN, N/NaN = NaN. The whole metric becomes NaN.
SCENARIO: One instance with a missing column propagates NaN through the entire aggregate score.
IMPACT: Report shows NaN as the overall score. Or shows 0.0 which is indistinguishable from "all terrible".
FIX: report.py:185-186 already handles this with clip(lower=0.001). get_report.py does NOT.
  Apply the same floor in get_report.py.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Failure Mode]
[LOCATION: report.py:261, get_report.py:168]
FINDING: multiprocessing.Pool with chunksize=1 — worst possible performance
EVIDENCE: pool.imap(worker, ds, chunksize=1)
SCENARIO: Dataset with 1000 instances -> 1000 IPC round-trips. Each task involves file I/O
  (reading perf_summary.txt, covering_test_status.json). IPC overhead dominates.
IMPACT: Report generation is 5-10x slower than it needs to be. On large datasets, minutes wasted.
FIX: Use chunksize=max(1, len(ds) // (num_workers * 4)) for better batching.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Failure Mode]
[LOCATION: report.py:131-132, get_report.py:114-115]
FINDING: FileNotFoundError if covering_test_status.json doesn't exist
EVIDENCE: (pred_run / instance_id / "covering_test_status.json").read_text()
  No existence check before reading.
SCENARIO: Evaluation ran but correctness postprocessing didn't produce the JSON file.
  The directory exists (so we pass the dir check on line 108) but the file doesn't.
IMPACT: Worker crash -> pool crash -> entire report fails.
FIX: Check file existence. Fall back to re-parsing raw outputs if JSON missing.
```

---

## 3. SECURITY & TRUST BOUNDARY AUDIT

```
[SEVERITY: MEDIUM]
[CATEGORY: Security]
[LOCATION: report.py:252-253]
FINDING: Local JSONL file loaded without sanitization
EVIDENCE:
  if dataset_path.exists() and dataset_path.suffix == ".jsonl":
  ds = [_json.loads(line) for line in _f if line.strip()]
SCENARIO: Adversarial JSONL with crafted instance data. Not a direct code execution risk,
  but instance_id could contain path traversal characters (../../etc/passwd).
  This flows into gold_run / instance_id / "perf_summary.txt" — reading arbitrary files.
IMPACT: Limited — reads file content as perf summary, would fail to parse. But information
  disclosure risk if error messages expose file contents.
FIX: Validate instance_id format (alphanumeric + limited punctuation only).
```

```
[SEVERITY: LOW]
[CATEGORY: Security]
[LOCATION: get_report.py:160]
FINDING: Hardcoded dataset name — no user control, but locked to specific HuggingFace repo
EVIDENCE: ds = datasets.load_dataset("swefficiency/swefficiency", split="test")
SCENARIO: If the HuggingFace repo is compromised, malicious data flows in.
IMPACT: Supply chain risk, but low probability.
FIX: Consider pinning a dataset version/commit hash.
```

---

## 4. CODE QUALITY & CORRECTNESS

```
[SEVERITY: HIGH]
[CATEGORY: Quality]
[LOCATION: get_report.py:59, get_lite_report.py:59]
FINDING: Typo in parameter name: use_correctnes_files (missing 's')
EVIDENCE: def evaluate_instance(..., use_correctnes_files=True)
SCENARIO: Caller passes use_correctness_files=False (correct spelling) -> TypeError: unexpected
  keyword argument. The API is broken by a typo.
IMPACT: The feature to disable correctness file reading cannot be used with correct spelling.
FIX: Rename to use_correctness_files.
```

```
[SEVERITY: HIGH]
[CATEGORY: Quality]
[LOCATION: get_report.py:111, get_lite_report.py:111]
FINDING: Typo in variable name: test_ouput_text (missing 't' in output)
EVIDENCE: test_ouput_text = test_output.read_text()
SCENARIO: Not a runtime bug (variable is used correctly on the next line), but indicates
  lack of code review and linting. Suggests other bugs may be hiding.
IMPACT: Maintenance burden, unprofessional.
FIX: Rename to test_output_text.
```

```
[SEVERITY: HIGH]
[CATEGORY: Quality]
[LOCATION: Three files are 90%+ identical]
FINDING: Massive code duplication — get_report.py, get_lite_report.py, and report.py share
  nearly identical code with subtle, critical divergences
EVIDENCE:
  - parse_perf_summary() — identical in all 3 files
  - get_number_of_patch_modified_lines() — identical in all 3 files
  - evaluate_instance() — nearly identical but with CRITICAL differences:
    * report.py handles string pass_to_pass, others don't
    * report.py has gold_perf_info fallback, others don't
    * report.py early return includes raw_pred_speedup_ratio, others don't
  - main()/generate_report() — structural duplicates with different features
SCENARIO: Bug fix applied to report.py is NOT propagated to get_report.py or get_lite_report.py.
  This has ALREADY HAPPENED — the string pass_to_pass handling was added to report.py but not the others.
IMPACT: The three "report" scripts produce DIFFERENT results for the SAME data. Which one is
  correct? Users don't know. Benchmark numbers vary by which script you run.
FIX: Delete get_report.py and get_lite_report.py. Make report.py the single source of truth.
  Add a --lite flag or --dataset parameter to report.py (it already has dataset_name parameter).
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Quality]
[LOCATION: get_report.py:186]
FINDING: base_speedup computed but never used
EVIDENCE: base_speedup = len(results_df) / (1 / results_df["pred_speedup_ratio"]).sum()
  This variable is never printed, returned, or referenced.
SCENARIO: Dead code — someone added it, forgot to use it, nobody noticed.
IMPACT: Wasted computation. More importantly, if someone intended to report it, a metric is missing.
FIX: Either use it (print/return) or delete it.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Quality]
[LOCATION: get_report.py:119, get_lite_report.py:119]
FINDING: failed_tests list built but never used
EVIDENCE:
  failed_tests = [] ... failed_tests.append(test) — collected but never referenced
SCENARIO: Dead code. Someone intended to report failing tests (see commented-out print block),
  but the list itself is wasted.
IMPACT: Minor memory waste, code noise.
FIX: Remove if not needed, or uncomment the reporting logic.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Quality]
[LOCATION: report.py:125-128, get_report.py:109-112]
FINDING: MAP_REPO_TO_PARSER lookup with no KeyError handling
EVIDENCE: MAP_REPO_TO_PARSER[instance["repo"]](test_output_text)
SCENARIO: Instance has a repo not in MAP_REPO_TO_PARSER. KeyError crashes the worker.
  (Note: MAP_REPO_TO_PARSER uses _ParserMapWithFallback which returns parse_log_pytest on
  __missing__, so this is actually safe — but only if you know the implementation detail.
  The code doesn't document this assumption.)
IMPACT: Low — saved by the fallback dict. But fragile and non-obvious.
FIX: Add a comment noting the fallback behavior, or use .get() with explicit default.
```

```
[SEVERITY: LOW]
[CATEGORY: Quality]
[LOCATION: get_report.py:128-138]
FINDING: Empty if block with pass — commented-out debug code
EVIDENCE:
  if correctness_pct < 1.0: followed by 8 commented-out lines and bare pass
SCENARIO: Dead code cluttering the function.
IMPACT: Noise. Makes the function harder to read.
FIX: Remove the entire if block or uncomment it behind a --verbose flag.
```

---

## 5. ARCHITECTURAL SMELLS

```
[SEVERITY: HIGH]
[CATEGORY: Architecture]
[LOCATION: Three report files]
FINDING: Shotgun surgery — three copies of the same logic, diverging silently
EVIDENCE: report.py (canonical), get_report.py (script), get_lite_report.py (lite variant)
  All three implement evaluate_instance() with subtle differences.
SCENARIO: ANY change to evaluation logic must be made in THREE places. History shows this
  has already failed (pass_to_pass string handling, gold_perf_info fallback, raw_pred_speedup_ratio).
IMPACT: Benchmark results depend on which script you run. Scientific reproducibility broken.
FIX: Single evaluate_instance() in report.py. Scripts import from report.py. get_lite_report.py
  just filters the dataset before calling the shared function.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Architecture]
[LOCATION: report.py — evaluate_instance()]
FINDING: Function does too many things — file I/O, parsing, grading, metric calculation
EVIDENCE: evaluate_instance() reads files, parses perf summaries, parses test statuses,
  computes correctness, computes speedup ratios, computes human speedup ratios, and assembles
  the result dict. ~100 lines, multiple return paths, two different patch_length calculations.
SCENARIO: Want to test the grading logic independently? Can't — it's entangled with file I/O.
IMPACT: Untestable. Any test requires mocking file system, which is why there are zero tests.
FIX: Decompose: parse_perf() (pure), grade_correctness(pred_statuses, pass_to_pass) (pure),
  compute_metrics(gold_perf, pred_perf, correctness) (pure), evaluate_instance() (I/O wrapper).
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Architecture]
[LOCATION: report.py:185-186]
FINDING: Business logic (0.001 floor) embedded in computation without domain justification
EVIDENCE:
  floored_human_speedup = df["human_speedup_ratio"].clip(lower=0.001)
  Comment says "capping effective gold speedup at 1000x" — but WHY 1000x? Is this a domain
  decision? A mathematical convenience? An arbitrary choice?
SCENARIO: Someone changes this to 0.01 or 0.0001 and benchmark scores shift significantly.
  No tests validate the behavior. No specification defines it.
IMPACT: Benchmark scores are sensitive to this magic number. Without specification, it's arbitrary.
FIX: Define this as a named constant with docstring explaining the domain rationale.
  Add tests that verify the behavior at boundary values.
```

---

## 6. STRESS TEST SCENARIOS

```
[SEVERITY: HIGH]
[CATEGORY: Stress Test]
[LOCATION: Scenario C — Silent corruption]
FINDING: The patch_length inconsistency (line 120 vs 157) produces silently wrong data
EVIDENCE: Instances taking early return (no correctness dir) get modified-line count.
  Instances taking normal path get total-line count. Both stored as "patch_length".
SCENARIO: A researcher plots "performance improvement vs patch complexity." The x-axis
  mixes two incompatible metrics. Conclusions drawn are invalid.
IMPACT: Published research uses corrupt data to draw conclusions.
FIX: Use one metric. Add a validation check that patch_length values are consistent.
```

```
[SEVERITY: HIGH]
[CATEGORY: Stress Test]
[LOCATION: Scenario F — Human error]
FINDING: get_report.py has a latent NameError that only manifests for missing gold runs
EVIDENCE: No gold_perf_info fallback -> NameError on gold_perf_info["before_mean"]
SCENARIO: New model evaluation where some instances don't have gold runs yet.
  Developer runs get_report.py -> crash. Switches to report.py -> works.
  "Why do these give different results?"
IMPACT: Hours of debugging. Wrong script used for months without noticing.
FIX: Eliminate get_report.py. One script, one truth.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Stress Test]
[LOCATION: Scenario A — Load]
FINDING: multiprocessing.Pool with chunksize=1 on large dataset
EVIDENCE: 1000+ instances x file I/O per instance x IPC overhead per task
SCENARIO: Report generation on full dataset takes 10+ minutes when it could take 1-2 minutes.
IMPACT: Developer feedback loop is slow. Quick iteration on scoring changes is painful.
FIX: Increase chunksize. Consider ThreadPoolExecutor (I/O-bound, GIL not an issue).
```

---

## 7. COMPARISON TO BEST PRACTICES

```
[SEVERITY: HIGH]
[CATEGORY: Best Practice]
[LOCATION: All three files]
FINDING: Zero test coverage for report generation — the PRIMARY output of the benchmark
EVIDENCE: No test files matching *report*. Zero unit tests for parse_perf_summary(),
  evaluate_instance(), compute_performance_breakdown(), or harmonic mean calculation.
SCENARIO: Any change to scoring logic is unverified. The patch_length inconsistency
  and missing gold_perf_info bugs would be caught by trivial unit tests.
IMPACT: Every bug described in this review could have been caught with ~20 lines of pytest.
FIX: Add tests for: parse_perf_summary (valid, empty, malformed), evaluate_instance
  (all code paths), harmonic_mean (edge cases), patch_length consistency.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Best Practice]
[LOCATION: report.py — generate_report()]
FINDING: generate_report() does I/O (file write) as a side effect — violates command-query separation
EVIDENCE: Function computes results AND writes CSV+JSON AND returns data.
SCENARIO: Want to compute the report in-memory without writing files? Can't.
  Want to write to a different format (Parquet, SQLite)? Must modify the function.
IMPACT: Inflexible. Testing requires temp directories.
FIX: Separate computation from persistence. Return results, let caller decide where to write.
```

```
[SEVERITY: MEDIUM]
[CATEGORY: Best Practice]
[LOCATION: report.py type annotations]
FINDING: Inconsistent typing — some functions annotated, some not. Annotations that exist are wrong.
EVIDENCE: generate_report() says -> pd.DataFrame but returns tuple.
  parse_perf_summary() has Dict[str, float]. evaluate_instance() has Dict (no parameterization).
  get_report.py's parse_perf_summary() has NO type annotations at all.
SCENARIO: Type checker would catch the return type lie — but no type checker runs in CI.
IMPACT: Types are decorative, not functional. Mislead rather than help.
FIX: Either commit to full typing (and run mypy/pyright in CI) or remove annotations that lie.
```

---

## 8. THE BRUTAL TRUTH

**Would I trust these report files to produce correct benchmark numbers for a published paper?**

No. The `patch_length` inconsistency alone means every published result table that includes patch complexity is using contaminated data. The divergence between report.py and get_report.py means results vary by which script you run. The missing `pass_to_pass` string handling in get_report.py means correctness metrics are completely wrong if the dataset uses JSON-encoded strings (which HuggingFace datasets commonly do).

**What is the #1 thing most likely to cause a production incident?**

The three-file duplication. It has ALREADY caused incidents — the gold_perf_info NameError, the missing raw_pred_speedup_ratio, the missing pass_to_pass deserialization. Every future change will cause more.

**Most dangerous assumption?**

That perf_summary.txt will always be well-formed with exactly 4 lines in the expected format. One corrupted file kills the entire report.

**Rating: Needs-work.**

The core metric design (harmonic mean of human speedup ratios with correctness gating) is sound. The `compute_performance_breakdown()` function in report.py is well-structured with the 0.001 floor for outlier protection. But the implementation has bugs that silently corrupt the primary output.

### Three things done WELL:

1. **compute_performance_breakdown()** in report.py — Clean decomposition of the scoring into meaningful buckets (incorrect, correct-no-speedup, correct-speedup-but-not-human, human-or-better). The 0.001 floor on harmonic mean prevents outlier domination. This is the most thoughtful function in all three files.

2. **Correctness gating** — The design of resetting speedup to 1.0 when correctness < 100% is the right approach. It prevents models from gaming the benchmark by producing fast-but-broken code.

3. **Local JSONL support** in report.py:249-253 — The ability to use a local file instead of HuggingFace makes offline development possible. Small but important for iteration speed.

---

## SCORING

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH | 10 |
| MEDIUM | 10 |
| LOW | 2 |
| **TOTAL** | **25** |

| Category | Count |
|----------|-------|
| Contradiction | 6 |
| Failure Mode | 5 |
| Security | 2 |
| Quality | 7 |
| Architecture | 3 |
| Stress Test | 3 |
| Best Practice | 3 |

### Top 5 Most Dangerous Issues

| Rank | Issue | Likelihood x Impact |
|------|-------|---------------------|
| 1 | **patch_length inconsistency** (two metrics, one name, same function) | HIGH x CRITICAL |
| 2 | **Three-file duplication with silent divergence** (already caused bugs) | HIGH x HIGH |
| 3 | **Missing pass_to_pass string handling** in get_report.py (all correctness metrics wrong) | HIGH x HIGH |
| 4 | **parse_perf_summary crash on malformed input** (one bad file kills everything) | MEDIUM x CRITICAL |
| 5 | **get_report.py NameError on missing gold run** (latent crash) | MEDIUM x HIGH |

**Confidence score: 35/100** — report.py alone is ~55/100 (the best of the three). But the existence of get_report.py and get_lite_report.py as divergent copies that produce different results for the same data drags the whole report infrastructure down. You cannot trust the benchmark numbers without knowing which script produced them.
