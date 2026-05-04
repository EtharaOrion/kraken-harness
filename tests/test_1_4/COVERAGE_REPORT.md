# Test Coverage Gaps & Summary Report

## Test Generation Summary

| Metric | Value |
|--------|-------|
| **Total Test Cases** | **653** (all passing) |
| **Test Files** | 9 (conftest + 8 test files) |
| **Production Files Covered** | 7 (all Stage 1 + Stage 2 public functions) |
| **Production Bugs Found** | 12 |

### By Priority

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | ~280 | Core logic: validation, filtering, API interaction, data pipeline |
| P1 | ~200 | Edge cases: null/empty, type coercion, boundary values |
| P2 | ~120 | String brutality, date edges, integration flows |
| P3 | ~53  | Performance, security, concurrency |

### By Category

| Category | Count |
|----------|-------|
| Unit | ~480 |
| Integration | ~35 |
| Parametrized Bulk | 134 |
| Security | ~8 |
| Performance | ~12 |

### By Dimension

| Dim | Name | Tests | Files | Notes |
|-----|------|-------|-------|-------|
| D1 | Input Domain | ~180 | 8/8 | Equivalence partitioning, BVA, pairwise — strong |
| D2 | Null/Empty/Missing | ~80 | 7/8 | None, empty string, whitespace, falsy, missing key — strong |
| D3 | Type Coercion | ~25 | 5/8 | Wrong types, integer-for-string, float precision — adequate |
| D4 | String Brutality | ~50 | 7/8 | Unicode, emoji, RTL, null bytes, injection — strong |
| D5 | Time/Date | ~20 | 3/8 | Midnight, leap year, epoch, 2038, DST — adequate (only relevant to 3 modules) |
| D6 | State/Lifecycle | ~12 | 3/8 | Resume/skip seen, caching, stale data — adequate |
| D7 | Concurrency | ~4 | 1/8 | Pool-based parallelism tested — **weak** (see gaps) |
| D8 | Error Handling | ~90 | 7/8 | 403/404/429 retry, exceptions, missing keys — strong |
| D9 | Security | ~10 | 3/8 | SSRF, log injection, token leakage — adequate for data pipeline |
| D10 | Data Format | ~12 | 3/8 | JSON, diff format, encoding — adequate |
| D11 | Performance | ~15 | 4/8 | Large inputs, many pages, bulk processing — adequate |
| D12 | Integration | ~20 | 5/8 | End-to-end pipelines, cross-function flows — adequate |

---

## Coverage Gaps Identified

### Gap 1: `extract_problem_statement_and_hints_django()` — UNTESTED (70 lines)

**File**: `collect/utils.py` lines 396-466
**What**: BeautifulSoup Trac HTML scraper for Django tickets
**Why gap exists**: Function uses `requests.get()` + `BeautifulSoup` for real HTML parsing. Would need HTML fixture files with realistic Trac ticket HTML, including:
- Two different timestamp formats (`mm/dd/yy HH:MM:SS` and `Mon DD, YYYY, HH:MM:SS AM/PM`)
- Table structure with `class='trac-field-owner'`
- Change history sections
- Multiple description/comment blocks

**Design flaw**: Returns `(str, list[tuple])` while non-django variant returns `(str, str)` — type mismatch. Callers must handle both signatures.

**Risk**: Medium. Django-specific, only triggered for `repo.name == "django"`.

### Gap 2: Concurrency / Race Conditions (D7) — WEAK

**What's tested**: `Pool(len(tokens))` is mocked, `starmap` is verified.
**What's NOT tested**:
- Actual parallel execution with shared state
- Race condition on file writes (two workers writing same output file)
- Token exhaustion under concurrent load
- Retry storm when multiple workers hit rate limit simultaneously

**Why**: Production uses `multiprocessing.Pool` which is hard to unit test. Would require integration tests with actual process spawning.

**Risk**: Low-medium. Production mitigates by splitting repos across tokens.

### Gap 3: `versioning/` — ZERO coverage (Stage 3)

**Files untested**:
- `versioning/get_versions.py` — Version detection, GitHub raw scraping, clone+build
- `versioning/constants.py` — MAP_REPO_TO_VERSION_PATHS, MAP_REPO_TO_VERSION_PATTERNS
- `versioning/utils.py` — get_instances, split_instances
- `versioning/extract_web/` — Web-based version extraction

**Why**: Out of scope for this test rewrite (Stage 1-2 only), but represents significant untested production code.

### Gap 4: D6 State/Lifecycle — Incomplete for `Repo.call_api`

**What's NOT tested**: 
- `call_api` behavior after Repo object enters "rate limited" state (multiple sequential 403s)
- Long-lived Repo object with expired token (token rotation)
- Repo object reuse across multiple pipeline stages

### Gap 5: D10 Data Format — Diff parsing edge cases

**What's tested**: Standard unified diff, test file separation, malformed diff, empty diff.
**What's NOT tested**:
- Binary file diffs (GIT binary patch)
- Rename diffs (`rename from/to`)
- Mode change diffs (`old mode/new mode`)
- No-newline-at-end-of-file marker
- Very long lines (>10K chars in a single diff line)
- Diff with >1000 hunks

**Why partially untestable**: `unidiff.PatchSet` handles parsing; we'd be testing the library, not our code. However, our split logic (`"test" in hunk.path`) could break on unusual paths.

---

## Critical Findings

### 1. Untestable Code Paths — DESIGN FLAWS Requiring Refactor

| Code | Issue | Impact |
|------|-------|--------|
| `send_request_with_rate_limit_handling()` | Infinite `while True` loop — unreachable `raise Exception("Too many retries")` at end | Dead code. No max-retry escape. A permanent 403 = infinite loop in production |
| `Repo.call_api()` | Same infinite `while True` with 5-minute sleep on 403 — no max retries | Same issue — permanent rate limit = hung process |
| `extract_problem_statement_and_hints_django()` | Returns different type signature than non-django variant | Silent type error for callers expecting `(str, str)` |
| `read_jsonl()` | Bare `except:` swallows `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` | Cannot ctrl+C during malformed file processing |

### 2. Implicit Assumptions Discovered — BUGS WAITING TO HAPPEN

| Code | Assumption | Reality |
|------|-----------|---------|
| `filter_base(pull, keywords=BASE_PERF_KEYWORDS)` | `keywords` param is used | Hardcoded to `BASE_PERF_KEYWORDS` — param ignored |
| `filter.py main()` line 77 | `filter_content` result contributes to filtering | Result overwritten by `False` — problem_statement keywords never used |
| `BASE_PERF_KEYWORDS` contains `"CPU usage"` | Will match in lowercased text | `"CPU usage"` has uppercase 'CPU', but `filter_base`/`filter_content` lowercase input before checking. `"cpu usage"` in the list would work, `"CPU usage"` never matches |
| `log_all_pulls()` uses `count >= max_pulls` | `max_pulls=N` logs N pulls | Actually logs N+1 pulls (count starts at 1, checked after write) |
| `get_gh_tokens()` calls `os.environ.get().split()` | Env var always exists | `os.environ.get()` returns `None` if missing → `None.split()` → `AttributeError` |
| `split_instances(list, 0)` | n > 0 always | `n=0` → `ZeroDivisionError` (no guard) |
| `BASE_PERF_KEYWORDS` has `"profiling"` twice | Unique keywords | Duplicate — wastes a comparison but doesn't break logic |

### 3. Missing Error Handling — PRODUCTION INCIDENTS

| Code | Missing Handling | Consequence |
|------|-----------------|-------------|
| `get_all_loop()` | `values` unbound if `num_pages` breaks before first empty page | `UnboundLocalError` in `logger.info` after loop |
| `extract_edits()` | No check for empty/malformed diff sections | `IndexError` on unexpected diff format |
| `construct_data_files()` | Broad `except Exception` catches everything including KeyboardInterrupt (Python 2 style) | In Python 3, fine — but masks real errors with just a print statement |
| `filter.py main()` | Empty PRs file → `pd.DataFrame([])['merged_at']` | `KeyError: 'merged_at'` — crash on empty input |

### 4. Uncovered Python-Specific Time Bombs

| Pattern | Location | Risk |
|---------|----------|------|
| `time.mktime(time.strptime(...))` | `_extract_hints()` | OS-dependent timezone handling. `time.mktime` uses local timezone, but GitHub timestamps are UTC. Results vary by server timezone |
| `dict(re.findall(...))` | `extract_resolved_issues()` | Silently deduplicates — last match wins. If PR says "fixes #1" and "closes #1", only one survives |
| Mutable default in `AttrDict` usage | Throughout collect/ | `AttrDict` objects from GhApi may share mutable state |

---

## Recommendations

### Highest Priority Tests to Write FIRST (ordered by risk)

1. **`extract_problem_statement_and_hints_django()`** — 70 lines of untested HTML scraping with two timestamp parsers. Create HTML fixtures for Trac ticket format.
2. **`versioning/` module** — Entire Stage 3 is untested. Start with `get_versions.py` version detection logic.
3. **Integration test: full `get_tasks_pipeline.main()`** with actual temporary files and real function calls (not mocked). Current tests mock everything.

### Architectural Changes Needed to Improve Testability

1. **Add max_retries parameter** to `send_request_with_rate_limit_handling()` and `Repo.call_api()`. Current infinite loops are untestable and dangerous.
2. **Fix `filter_base` to use `keywords` parameter** instead of hardcoded `BASE_PERF_KEYWORDS`.
3. **Fix `filter.py main()` line 77** — remove the `is_perf = False` override that kills `filter_content` results.
4. **Normalize `BASE_PERF_KEYWORDS`** — lowercase `"CPU usage"` → `"cpu usage"`, remove duplicate `"profiling"`.
5. **Fix type mismatch** — `extract_problem_statement_and_hints_django()` should return `(str, str)` like the non-django variant.
6. **Replace bare `except:` in `read_jsonl()`** with `except (json.JSONDecodeError, ValueError):`.
7. **Add guard for `n=0`** in `split_instances()`.
8. **Add guard for missing env var** in `get_gh_tokens()` — return empty list or raise descriptive error.

### Monitoring/Observability Gaps That Testing Cannot Cover

1. **Rate limit exhaustion** — No monitoring for how often workers hit 403/429 in production. Could be silently sleeping for hours.
2. **Trac scraper failures** — Django ticket format changes would silently return empty results. No alerting.
3. **Token rotation** — No mechanism to detect expired GitHub tokens. Workers will infinite-loop on 401 (not handled by retry logic).
4. **Pipeline progress** — No checkpoint/resume mechanism beyond the `.all` file. A crash loses all in-flight work for that repo.
