# kraken-harness

The harness for the kraken RL gym. One entry point, every stage from a merged pull
request to a reward.

```
kraken-harness/
├── kraken.py            harvest | author | run | grade | status
├── kraken_rollout.py    drives an agent against a bundle
├── kraken_judge.py      scores the rubric channel outside the container
├── kraken_validate.py   deterministic corpus checks
├── repo2rlenv/          the generator library and its own test suite
└── harbor/              the runtime that executes a task against an agent
```

## Stages

| Command | What it does |
|---|---|
| `harvest` | Mines merged pull requests into candidate corpus records. Selection reads the PR title and body, never the diff, so the corpus is not biased toward one shape of fix. |
| `author` | Builds the content-addressed image, calibrates the target in the graded container, proves both reward endpoints, and emits the bundle. |
| `run` | Drives an agent. Prefers `harbor`, falls back to `kraken_rollout.py`. |
| `grade` | Scores the rubric channel and recomposes the reward. Separate because the graded container has no network by design. |

Stages stay separate because harvest loads the network while author needs a quiet
host. One button would run measurement under load and hide which stage failed.

## Usage

```bash
uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py <stage>
```

## What is not here

`pilot/` lives at the knowledge root, not in the harness. FORGE Phase 4 is out-of-band
only and the repository may never self-produce trusted difficulty proof, so keeping the
pilot outside is what makes its externality structural rather than promised.

`references/swefficiency` is the published implementation this delivery conforms to. It
is vendored at the knowledge root, off the build path, and nothing here imports it.
