# `perf_runtime`

**Repository-level performance optimization.** The agent gets a real codebase at a
pre-optimization commit and a timed workload, and must make the workload faster
without changing behavior.

Stability: **experimental**. Sandbox: yes. LLM at generation: **none**. Languages: Python.

## When to use it

Use it when you want the *how to fix* regime rather than *what to fix*. Every other
runtime pipeline scores a test transition: something was red, the patch makes it
green. This one scores a measured runtime ratio while the tests stay green the whole
way through. The failure it induces is the one performance engineers actually hit:
a change that is faster and subtly wrong.

## Input contract

Corpus-driven rather than scrape-driven. The harvest is assumed solved upstream, and
each record is one JSON object per line:

| Field | Meaning |
|---|---|
| `instance_id`, `repo`, `base_commit` | Identity and the commit the task starts from |
| `patch` | The reference optimization. Must be a well-formed unified diff |
| `test_patch` | Held-out tests, applied at grade time |
| `problem_statement` | Source text for the agent-visible brief |
| `covering_tests`, `test_cmd` | The correctness set and how to run it |
| `workload` | The timed script, agent-visible, printing `Mean: <seconds>` |
| `speedup` | The expert ratio measured upstream, used as a cross-check only |
| `python_version`, `install_cmd`, `pre_install_cmds` | The environment spec |
| `created_at` | Becomes the mandatory per-instance provenance date |

A record missing any mandatory field is excluded with its reason recorded.

```bash
repo2rlenv generate --pipeline perf_runtime \
  --pipeline-opt corpus=./harvest --pipeline-opt limit=0 \
  --out ./datasets/perf
```

## Why no LLM

The corpus already carries the install command, the runtime version, and the test
command, so the Dockerfile is a deterministic function of the record. Nothing is
inferred, so nothing needs a model and nothing varies between runs. A judge model is
invoked only at grade time by the rubric channel, through the task's declared
environment block rather than baked into the image.

## Admission gates

A bundle is emitted only after it survives all of these, in order. Each gate is cheap
before the gate after it, so a bad instance is rejected before it costs a build.

1. **Diff well-formedness.** Every hunk header must reconcile with its body. A
   truncated reference patch cannot apply, which makes the reward ceiling unreachable.
   That is a broken task, not a hard one.
2. **Target calibration.** The reference patch is run through the graded path in the
   built container, three times. The bound target becomes the median ratio it actually
   reached *here*, not the ratio measured on the harvest host. A corpus target that
   does not reproduce in the graded environment is a ceiling nobody has shown to be
   attainable.
3. **Measurability.** The oracle gain must exceed twice its own measurement noise. A
   gain inside the noise band is rejected with the numbers that rejected it.
4. **Endpoint calibration.** The reference patch must score exactly `1.0` and an empty
   submission exactly `0.0`, on the shipped image through the shipped verifier.
5. **Reward stability.** Three whole-verifier re-runs on the same patch must produce
   an identical reward to four decimal places. A reward that moves is not a reward.

## Reward

Items are binary; the composition is continuous.

```
reward = sum(weights of passed scored items) / sum(all positive scored weights)
```

Zero overrides, checked before anything else and each carrying a machine-readable
reason: an empty or no-op patch, a patch that fails to apply, a crossed red line, a
confirmed reward hack, a failed correctness gate, an unstable measurement.

The speed signal is four binary bands at 25, 50, 75, and 100 percent of the expert
gain, which is how a single measured ratio becomes a continuous reward. A run that
recovers part of the expert gain earns part of the points.

Correctness is a **precondition**, not a weighted contributor: if the covering tests
fail, the reward is zero and the rubric is never consulted.

An unscored rubric criterion, meaning no judge key reached the verifier, leaves the
denominator entirely. It awards nothing and costs nothing, so the golden endpoint
stays reachable when a channel cannot run.

## Emitted layout

```
<uuid>/
  task.toml                  manifest, image pinned by @sha256:, provenance
  instruction.md             the only agent-visible brief
  environment/Dockerfile     FROM the prebuilt digest, so a rollout pulls
  environment/test_patch.diff
  tests/                     test.sh, verify.py, measure.py, grade.py, workload.py,
                             test_outputs.py, test_weights.json, rubric.json, targets.json
  solution/                  patch.diff, solve.sh, TRUTH.md, grounding.yaml, recompute.py
```

`solution/grounding.yaml` is the single derivation source. `solution/recompute.py`
regenerates the ground truth, the oracle, the fixtures, the weights, and the rubric
from it in one pass, so the truth a reviewer reads, the fixtures the checkers assert,
and the oracle the harness runs cannot disagree. Regeneration is byte-identical;
drift is a blocking defect.

## Measurement discipline

Bound values, applied to every graded runtime target:

| Parameter | Value |
|---|---|
| Trials per condition | 5, aggregated by median |
| Warmup | 3 invocations, discarded |
| Isolation | one process per repetition |
| Pinning | one physical core where the platform supports it |
| Variance ceiling | coefficient of variation 0.05, above which the run reports unstable |
| Baseline | re-timed on the same container, back to back with the optimized run |

The baseline is measured after the optimized condition, on the same container, so the
ratio is not confounded by host noise between image builds.

## Known limits

- The corpus `speedup` is a cross-check, not the graded target. Expect the calibrated
  target to differ, sometimes by a lot, and treat a large divergence as a signal about
  the harvest host rather than about the task.
- Small-gain instances are frequently rejected. At a few percent over a workload of a
  few tens of milliseconds, the gain and the noise are the same size, and no amount of
  reward design fixes that.
- The rubric channel needs judge keys at grade time. Without them the criteria are
  unscored and the reward rests on the measured and deterministic channels alone.
