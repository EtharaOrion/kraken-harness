# Test Report — Stage 1 & Stage 2 (test_1_4)

**Project**: SWE-fficiency  
**Test Directory**: `tests/test_1_4/`  
**Date**: April 24, 2026  
**Python**: 3.12.13 | **pytest**: 9.0.3  
**Result**: **10,012 passed** in 6.09s

---

## Summary

| Metric | Value |
|---|---|
| Total tests | 10,012 |
| Passed | 10,012 |
| Failed | 0 |
| Errors | 0 |
| Duration | 6.09s |
| Test files | 8 (+1 conftest) |
| Total lines of test code | 9,912 |
| Production functions covered | 42 |
| Production bugs documented | 17 |

---

## Test Distribution by File

| File | Tests | Lines | Production Target |
|---|---|---|---|
| `test_bulk.py` | 4,003 | 2,199 | Cross-cutting bulk/stress tests across all Stage 1 & 2 functions |
| `test_build_dataset.py` | 1,811 | 1,116 | `collect/build_dataset.py` — `is_valid_pull`, `is_valid_instance`, `has_test_patch`, `create_instance`, `main` |
| `test_constants.py` | 1,620 | 1,662 | `perf_filter/attributes/constants.py` — keywords, `check_labels`, `remove_markdown_comments`, `filter_base`, `filter_content`, 17 per-repo filters |
| `test_collect_utils.py` | 1,127 | 2,313 | `collect/utils.py` — `Repo` class, `call_api`, `extract_resolved_issues`, `get_all_loop`, `extract_patches`, `send_request_with_rate_limit_handling`, `_extract_hints`, `extract_problem_statement_and_hints`, `extract_problem_statement_and_hints_django` |
| `test_get_tasks_pipeline.py` | 577 | 456 | `collect/get_tasks_pipeline.py` — `split_instances`, `construct_data_files`, `main` |
| `test_perf_filter_utils.py` | 411 | 925 | `perf_filter/utils.py` — `extract_edits`, `read_jsonl`, `get_gh_tokens`, `is_doc_file`, `has_lock_file_change` |
| `test_print_pulls.py` | 235 | 464 | `collect/print_pulls.py` — `log_all_pulls`, `main` |
| `test_filter.py` | 228 | 484 | `perf_filter/attributes/filter.py` — `is_perf_pr`, `main` |
| `conftest.py` | — | 293 | 15 shared fixtures |

---

## Production Code Coverage Map

### Stage 1: Data Collection (`collect/`)

| Function | File | Tests | Dimensions |
|---|---|---|---|
| `Repo.__init__` | `utils.py` | 8 | D1, D2, D3, D4, D8 |
| `Repo.call_api` | `utils.py` | 7 | D1, D2, D3, D6, D8 |
| `Repo.extract_resolved_issues` | `utils.py` | 968 | D1, D2, D4, D9, D10, D11 |
| `Repo.get_all_loop` | `utils.py` | 12 | D1, D2, D6, D8, D11 |
| `Repo.get_all_issues` | `utils.py` | 2 | D1 |
| `Repo.get_all_pulls` | `utils.py` | 2 | D1 |
| `extract_problem_statement_and_hints` | `utils.py` | 9 | D1, D2, D4, D6, D8, D12 |
| `extract_problem_statement_and_hints_django` | `utils.py` | 27 | D1, D2, D4, D5, D8, D9, D11, D12 |
| `_extract_hints` | `utils.py` | 11 | D1, D2, D5 |
| `send_request_with_rate_limit_handling` | `utils.py` | 57 | D1, D2, D3, D4, D5, D8, D9, D10 |
| `extract_patches` | `utils.py` | 16 | D1, D2, D4, D8, D10, D11 |
| `is_valid_pull` | `build_dataset.py` | 916 | D1, D2, D3, D4, D5, D8 |
| `is_valid_instance` | `build_dataset.py` | 850 | D1, D2, D3, D4, D8 |
| `has_test_patch` | `build_dataset.py` | 963 | D1, D2, D3, D4, D8, D11 |
| `create_instance` | `build_dataset.py` | 20 | D1, D2, D4, D8, D12 |
| `main` (build_dataset) | `build_dataset.py` | 15 | D1, D2, D6, D8, D9, D10, D11 |
| `log_all_pulls` | `print_pulls.py` | 65 | D1, D2, D5, D8, D11 |
| `main` (print_pulls) | `print_pulls.py` | 8 | D1, D2, D3, D4, D8 |
| `split_instances` | `get_tasks_pipeline.py` | 1,262 | D1, D2, D3, D4, D8, D11, D12 |
| `construct_data_files` | `get_tasks_pipeline.py` | 11 | D1, D2, D4, D5, D6, D8 |
| `main` (pipeline) | `get_tasks_pipeline.py` | 8 | D1, D4, D7, D8 |

### Stage 2: Performance Filtering (`perf_filter/`)

| Function | File | Tests | Dimensions |
|---|---|---|---|
| `extract_edits` | `utils.py` | 15 | D1, D2, D4, D8, D11 |
| `read_jsonl` | `utils.py` | 15 | D1, D2, D4, D8, D10, D11 |
| `get_gh_tokens` | `utils.py` | 9 | D1, D2, D4 |
| `is_doc_file` | `utils.py` | 691 | D1, D2, D4, D9 |
| `has_lock_file_change` | `utils.py` | 261 | D1, D2, D4 |
| `VERBATIM_KEYWORDS` | `constants.py` | 7 | D1, D2 |
| `BASE_PERF_KEYWORDS` | `constants.py` | 7 | D1, D2 |
| `check_labels` | `constants.py` | 461 | D1, D2, D4 |
| `remove_markdown_comments` | `constants.py` | 362 | D1, D2, D4, D11, D12 |
| `filter_base` | `constants.py` | 658 | D1, D2, D4, D8 |
| `filter_content` | `constants.py` | 406 | D1, D2, D4, D8 |
| `filter_sklearn` | `constants.py` | 28 | D1 |
| `filter_astropy` | `constants.py` | 8 | D1 |
| `filter_matplotlib` | `constants.py` | 8 | D1 |
| `filter_pylint` | `constants.py` | 8 | D1 |
| `filter_seaborn` | `constants.py` | 8 | D1 |
| `filter_sphinx` | `constants.py` | 8 | D1 |
| `filter_sympy` | `constants.py` | 8 | D1 |
| `filter_xarray` | `constants.py` | 9 | D1 |
| `filter_dask` | `constants.py` | 24 | D1 |
| `filter_pandas` | `constants.py` | 9 | D1 |
| `filter_numpy` | `constants.py` | 8 | D1 |
| `filter_statsmodels` | `constants.py` | 8 | D1 |
| `filter_pillow` | `constants.py` | 8 | D1 |
| `filter_spacy` | `constants.py` | 8 | D1 |
| `filter_numba` | `constants.py` | 8 | D1 |
| `filter_gensim` | `constants.py` | 8 | D1 |
| `filter_scikit_image` | `constants.py` | 8 | D1 |
| `REPO_PERF_FILTERS` | `constants.py` | 5 | D1, D12 |
| `is_perf_pr` | `filter.py` | 525 | D1, D2, D12 |
| `main` (filter) | `filter.py` | 12 | D1, D2, D4, D8, D12 |

---

## 12-Dimension Coverage

| Dimension | Description | Tests | Coverage |
|---|---|---|---|
| **D1** Input Domain | Equivalence partitioning, BVA, pairwise | ~6,500 | Full — every public function has standard + boundary inputs |
| **D2** Null/Empty/Missing | None, empty string, empty collection, whitespace, zero, falsy | ~800 | Full — None/empty/whitespace/falsy tested for all accepting functions |
| **D3** Type Coercion | Wrong types, float precision, overflow | ~200 | Covered — int/float/bool/complex/bytes/callable as merged_at; float('inf')/float('-inf') |
| **D4** String Brutality | Unicode, emoji, RTL, control chars, injection | ~600 | Covered — unicode multi-byte, emoji, RTL, combining diacriticals, null bytes, log injection |
| **D5** Time/Date | Midnight, DST, leap year, epoch, 2038 | ~300 | Covered — epoch zero, year 2038, midnight, AM/PM parsing, year/month/day exhaustive |
| **D6** State/Lifecycle | Empty, populated, corrupted, mid-transition | ~30 | Partial — resume from .all file, rate limit state transitions, pagination state |
| **D7** Concurrency | Race conditions, Pool usage | ~8 | Minimal — Pool(len(tokens)) verified, not real concurrent execution |
| **D8** Error Handling | Every error path, retries, cascading | ~200 | Full — 403/404/429/500/502, retry-after headers, rate limit backoff, broad except handling |
| **D9** Security | Injection, SSRF, token exposure, path traversal | ~15 | Partial — SSRF URL, log injection, path traversal in issue_number, token[:10] crash |
| **D10** Data Format | Encoding, JSON edge cases, line endings | ~30 | Partial — JSONL parsing, malformed JSON, diff format, BOM/CRLF not tested |
| **D11** Performance | Large payloads, scaling | ~150 | Covered — 10K char bodies, 50-file diffs, 100-page pagination, long strings |
| **D12** Integration | Cross-function interactions | ~80 | Covered — pipeline integration, filter dispatch, whitespace asymmetry |

---

## Production Bugs Documented in Tests

| # | Bug | Location | Severity | Test |
|---|---|---|---|---|
| 1 | `CPU usage` keyword uppercase but `filter_base`/`filter_content` lowercase text — can never match | `constants.py` L78 | Medium | `TestFilterBase::test_d8_cpu_usage_keyword_uppercase_bug` |
| 2 | `filter_base` hardcodes `BASE_PERF_KEYWORDS` instead of using `keywords` parameter | `constants.py` L73 | Medium | `TestFilterBase::test_d8_keywords_param_ignored_bug` |
| 3 | `filter.py main()` line 77 overrides `filter_content` result with `False` | `filter.py` L77 | High | `TestMainFilterPipeline::test_d8_problem_statement_keywords_overridden_bug` |
| 4 | `BASE_PERF_KEYWORDS` has duplicate `'profiling'` | `constants.py` | Low | `TestKeywordConstants::test_d2_base_keywords_has_duplicate_profiling` |
| 5 | 8 per-repo filters are case-sensitive on title, 9 lowercase — inconsistent | `constants.py` | Medium | `TestFilterPandas`, `TestFilterNumpy`, etc. |
| 6 | `self.token[:10]` TypeError when token is None during 403 handling | `utils.py` L68 | High | `TestCallApi::test_d3_none_token_crashes_on_403_slice` |
| 7 | `issue_number = issue.number` reassigns loop variable from resolved_issues | `utils.py` L273 | Medium | `TestExtractProblemStatementAndHints::test_d6_issue_number_reassigned` |
| 8 | `.strip(",").strip()` order bug — commas survive when whitespace is outermost | `get_tasks_pipeline.py` L73 | Low | `TestConstructDataFiles::test_d4_repo_name_comma_then_whitespace` |
| 9 | `lines[N].split()[1]` IndexError on malformed diff lines | `utils.py` L41-42 | Medium | `TestExtractEdits::test_d8_line_with_no_spaces_causes_index_error` |
| 10 | Bare `except:` in `read_jsonl` swallows `KeyboardInterrupt`/`SystemExit` | `utils.py` L66 | High | `TestReadJsonl::test_d8_bare_except_swallows_keyboard_interrupt` |
| 11 | `split_instances` ZeroDivisionError if `n=0` | `get_tasks_pipeline.py` L40 | Medium | `TestSplitInstances::test_d8_zero_n_raises` |
| 12 | `get_gh_tokens` AttributeError if env var missing — `None.split()` | `utils.py` L73 | High | `TestGetGhTokens::test_d2_missing_env_var_raises` |
| 13 | `log_all_pulls` off-by-one: `max_pulls=N` writes `N+1` pulls (`>=` check after write) | `print_pulls.py` L62 | Medium | `TestLogAllPulls::test_d1_max_pulls_limits_output` |
| 14 | `extract_problem_statement_and_hints_django` returns `(str, list[tuple])` not `(str, str)` | `utils.py` | Medium | `TestExtractProblemStatementAndHintsDjango::test_d12_return_type` |
| 15 | `send_request_with_rate_limit_handling` has unreachable code at end of infinite loop | `utils.py` L358 | Low | Documented in class docstring |
| 16 | `extract_edits` variable names counter-intuitive: `source_file_name` holds dest path | `utils.py` L41-42 | Low | `TestExtractEdits::test_d1_source_dest_variable_semantics` |
| 17 | `'attestation'` contains `'test'` → false positive in test file classification | `utils.py` | Low | `TestExtractPatches::test_d4_substring_false_positive` |

---

## Uncovered Areas (Known Gaps)

### Stage 3: Version Detection — ZERO coverage
No test files exist for `versioning/get_versions.py`, `versioning/constants.py`, `versioning/utils.py`, or `versioning/extract_web/`.

### Dimension Gaps
- **D7 Concurrency**: No real concurrent execution tests (multiprocessing.Pool usage verified structurally only)
- **D9 Security**: Missing comprehensive SSRF, SQL injection, XSS vectors
- **D10 Data Format**: Missing BOM, CRLF line endings, encoding mismatch tests
- **D6 State**: No corrupted file recovery, cleanup failure, or mid-transition state tests

### Prompt Compliance Gaps
- **Phase 1 Reconnaissance**: 10-question-per-function analysis not formally documented
- **Phase 5 Master Interrogation**: 25-question-per-function analysis not formally documented
- **Test case tables**: Per-function dimension/priority/category tables not included inline

---

## Test Class Inventory (Top 30 by test count)

| Class | Tests | Target Function |
|---|---|---|
| `TestMassiveExtractResolvedIssues` | 945 | `extract_resolved_issues` — keyword × issue 1-100 cross-product |
| `TestMassiveHasTestPatchExpanded` | 694 | `has_test_patch` — whitespace/char/length variants |
| `TestMassiveSplitInstancesExpanded` | 540 | `split_instances` — size × n cross-products |
| `TestMassiveIsValidInstanceExpanded` | 515 | `is_valid_instance` — ASCII/length/space/newline variants |
| `TestMassiveIsValidPullExpanded` | 420 | `is_valid_pull` — year/int/char/negative variants |
| `TestMassiveSplitInstances` | 334 | `split_instances` — shape/identity/element/type tests |
| `TestWave2IsValidPullDates` | 312 | `is_valid_pull` — year 2000-2025 × month 1-12 |
| `TestWave2SplitInstancesPreservation` | 250 | `split_instances` — element preservation |
| `TestMassiveFilterBaseExpanded` | 243 | `filter_base` — keyword position/case variants |
| `TestMassiveIsDocFileExpanded` | 231 | `is_doc_file` — extensions/prefixes/depths |
| `TestMassiveIsValidPull` | 229 | `is_valid_pull` — merged_at date/type/string variants |
| `TestMassiveHasTestPatch` | 227 | `has_test_patch` — valid/invalid/char/whitespace |
| `TestMassiveIsPerfPrExpanded` | 206 | `is_perf_pr` — repo/keyword/VERBATIM cross |
| `TestMassiveIsValidInstance` | 200 | `is_valid_instance` — valid/invalid/length/char |
| `TestWave2FilterBaseAllKeywordsBody` | 196 | `filter_base` — all keywords × 7 body templates |
| `TestMassiveRemoveMarkdownCommentsExpanded` | 195 | `remove_markdown_comments` — n-comments/text-between |
| `TestMassiveFilterBase` | 188 | `filter_base` — body/title keywords, HTML comment hiding |
| `TestWave2IsPerfPrKeywordBodyCross` | 180 | `is_perf_pr` — 18 repos × 10 keywords in body |
| `TestMassiveIsDocFile` | 170 | `is_doc_file` — doc/non-doc/prefixes/backup |
| `TestWave2IsDocFileWithDirectories` | 160 | `is_doc_file` — 10 dirs × 8 filenames × 2 extensions |
| `TestMassiveCutoffDateExpanded` | 152 | Cutoff date parsing — year/month/day exhaustive |
| `TestWave2CheckLabelsSubstringMatrix` | 144 | `check_labels` — 12 labels × 12 values |
| `TestWave2CheckLabelsExhaustive` | 140 | `check_labels` — self-match/prefix/unrelated |
| `TestMassiveFilterContentExpanded` | 139 | `filter_content` — keyword/case/comment/non-matching |
| `TestMassiveCheckLabelsExpanded` | 132 | `check_labels` — self-match/n-labels/n-values |
| `TestWave2HasTestPatchMixedWhitespace` | 125 | `has_test_patch` — 5³ whitespace char combos |
| `TestWave2IsValidPullTimestampVariants` | 120 | `is_valid_pull` — 24 hours × 5 minutes |
| `TestWave2IsDocFileNonDoc` | 118 | `is_doc_file` — 59 non-doc extensions × 2 |
| `TestWave2FilterContentAllKeywords` | 112 | `filter_content` — all keywords × 4 case variants |
| `TestMassiveIsPerfPr` | 111 | `is_perf_pr` — registered/unregistered/fallback |

---

## Run Command

```bash
cd "/Users/apple/Desktop/Work/KRAKEN NEW/SWE-fficiency"
python -m pytest tests/test_1_4/ -v
```
